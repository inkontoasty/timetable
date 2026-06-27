import discord
from discord.ext import commands
import yt_dlp,asyncio,random,ytmusicapi,spotify_scraper,time,youtube_transcript_api,requests,bs4,unicodedata
from const import MAX_SONGS,AZ

bot = None
azf = lambda x:''.join(i for i in unicodedata.normalize('NFD',x).encode('ascii', 'ignore').decode('utf-8').lower() if i in 'qwertyuiopasdfghjklzxcvbnmQWERTYUIOPASDFGHJKLZXCVBNM1234567890')or'e'

class Song:
    def __init__(self,qidx=-1,**kwargs):
        self.id = kwargs.get('id')
        self.spotify = kwargs.get('spotify')
        self.title = kwargs.get('title','a')
        self.artists = kwargs.get('artists',[])
        if self.title.startswith(">> "): self.title = "}} "+self.title[3:]
        self.url = kwargs.get('url')
        self.queued = kwargs.get('queued')
        self.lyrics = kwargs.get('lyrics')
        self.duration = int(kwargs.get('duration',0))
        self.qidx = qidx # unique i hope
    def fmt(self):
        if self.artists: return f"{self.title} - {', '.join(self.artists)}"
        else: return self.title
    def __eq__(self,other): return self.qidx==other.qidx
    def __repr__(self): return f'{self.qidx} {self.title} {self.id} {self.url}'
    def copy(self,qidx=-1): return Song(qidx,id=self.id,spotify=self.spotify,title=self.title,duration=self.duration,
                                        url=self.url,queued=self.queued,lyrics=self.lyrics,artists=self.artists)

class Source(discord.PCMVolumeTransformer):
    def __init__(self, original):
        super().__init__(original, 1.0)
        self.start_time = 0.0
        self.frames_read = 0
        self.sample_rate = 48000  # Standard Opus sample rate
        self.channels = 2         # Stereo
    def read(self):
        result = super().read()
        if result: # Each PCM frame is 20ms of audio (960 samples per channel)
            self.frames_read += 1
            self.start_time = self.frames_read * 0.02
        return result
    @property
    def stream_time(self):
        return self.start_time

class EditModal(discord.ui.Modal,title="edit queue"):
    def __init__(self,player):
        super().__init__(timeout=None)
        self.player = player
        self.qmap = {i.fmt()[:100]:i for i in player.queue}
        self.ins = []
        stuff = []
        leng = 0
        for n,i in enumerate(player.queue):
            x=i.fmt()[:100]
            if n==player.cidx: x = '>> ' + x
            if leng+len(x) > 4000:
                self.ins.append(discord.ui.TextInput(
                    label=str(len(self.ins)+1),
                    default="\n".join(stuff),
                    style=discord.TextStyle.paragraph,required=False)
                )
                leng = 0
                stuff = []
            stuff.append(x)
            leng += len(x)+1
        if stuff: 
            self.ins.append(discord.ui.TextInput(
                label=str(len(self.ins)+1),
                default="\n".join(stuff),
                style=discord.TextStyle.paragraph,required=False)
            )
        for i in self.ins[:5]:
            try:self.add_item(i)
            except Exception as e:print(e)
    async def on_submit(self,i):
        queue = []
        cidx = -1
        n=0
        errors = []
        for x in '\n'.join(i.value for i in self.ins).strip().split('\n'):
            if x in self.qmap:
                queue.append(self.qmap[x].copy(n))
            elif x.startswith('>> ') and x[3:] in self.qmap:
                if cidx==-1: cidx = n
                queue.append(self.qmap[x[3:]].copy(n))
            else:
                errors.append(f'couldnt find "{x}"')
                n -= 1
            n += 1
            if n>=MAX_SONGS:
                errors.append(f'max queue length is {MAX_SONGS} songs, disregarding subsequent input')
                break
        current = self.player.queue[self.player.cidx].fmt() if not self.player.cidx==len(self.player.queue) else -1
        if cidx==-1: cidx=len(queue)
        self.player.queue = queue
        self.player.cidx = cidx
        self.player.shuffle = False
        self.player.shufflebtn.label = "shuffle"
        self.player.shufflebtn.style = discord.ButtonStyle.blurple
        if current!=-1 and cidx==len(queue):
            errors.append('no >> pointer found, skipping to the end')
        if errors: await i.response.send_message('\n'.join(errors)[:2000],ephemeral=True,delete_after=20)
        else: await i.response.defer()
        if current!=(queue[cidx].fmt() if cidx<len(queue) else -1):
            self.player.cidx -= 1
            await self.player.fnext()
        else:
            self.player.loadurl(self.player.cidx+1)
            await self.player.frefresh()

class LyricsModal(discord.ui.Modal):
    def __init__(self,song):
        super().__init__(timeout=None,title="info")
        c = f'''
{song.fmt()}
{(song.duration//60)%60:02}:{song.duration%60:02}
https://www.youtube.com/watch?v={song.id}
{song.spotify or ""}
{song.lyrics or "loading lyrics - pls reopen popup"}'''.split('\n')
        s = 0
        a=[]
        n=0
        for i in c:
            if s+len(i)>4000:
                if n==0: self.add_item(discord.ui.TextDisplay(content='\n'.join(a)))
                else: self.add_item(discord.ui.TextInput(label=f'{n+1}',default='\n'.join(a),style=discord.TextStyle.paragraph,required=False))
                s=0
                a=[]
                n+=1
                if n>=5:return
            a.append(i)
            s+=len(i)+1
        if a:
            if n==0: self.add_item(discord.ui.TextDisplay(content='\n'.join(a)))
            else:self.add_item(discord.ui.TextInput(label=f'{n+1}',default='\n'.join(a),style=discord.TextStyle.paragraph,required=False))
    async def on_submit(self,i):await i.response.defer()

class PlayerView(discord.ui.LayoutView):
    def __init__(self,guild,msg):
        self.msg = msg
        self.guild = guild
        self.cidx = 0
        self.queue = []
        self.paused = False
        self.forcepaused = False
        self.shuffle = False
        self.disconnect = 0

        super().__init__(timeout=None)
        self.txtdisplay = discord.ui.TextDisplay(content='yo')
        self.add_item(self.txtdisplay)
        row = discord.ui.ActionRow()
        self.select = discord.ui.Select(max_values=1,options=[discord.SelectOption(label='yo',default=True)])
        row.add_item(self.select)
        self.add_item(row)
        row = discord.ui.ActionRow()
        self.prevbtn = discord.ui.Button(label='prev',style=discord.ButtonStyle.blurple)
        self.playbtn = discord.ui.Button(label='pause',style=discord.ButtonStyle.blurple)
        self.nextbtn = discord.ui.Button(label='next',style=discord.ButtonStyle.blurple)
        self.shufflebtn = discord.ui.Button(label='shuffle',style=discord.ButtonStyle.blurple)
        row.add_item(self.prevbtn)
        row.add_item(self.playbtn)
        row.add_item(self.nextbtn)
        row.add_item(self.shufflebtn)
        self.add_item(row)
        row = discord.ui.ActionRow()
        self.clearbtn = discord.ui.Button(label='clear',style=discord.ButtonStyle.red)
        self.leavebtn = discord.ui.Button(label='leave',style=discord.ButtonStyle.red)
        self.editbtn = discord.ui.Button(label='edit',style=discord.ButtonStyle.blurple)
        self.lyricsbtn = discord.ui.Button(label='lyrics',style=discord.ButtonStyle.blurple)
        row.add_item(self.clearbtn)
        row.add_item(self.leavebtn)
        row.add_item(self.editbtn)
        row.add_item(self.lyricsbtn)
        self.add_item(row)
        
        self.btns = [self.prevbtn,self.nextbtn,self.clearbtn,self.playbtn,self.leavebtn,self.shufflebtn,self.editbtn,self.lyricsbtn]
        self.nextbtn.callback = self.fnext
        self.clearbtn.callback = self.fclear
        self.playbtn.callback = self.fpause
        self.prevbtn.callback = self.fprev
        self.leavebtn.callback = self.fleave
        self.shufflebtn.callback = self.fshuffle
        self.select.callback = self.fselect
        self.editbtn.callback = self.fedit
        self.lyricsbtn.callback = self.flyrics

    async def check(self,i,defer=True):
        if not self.guild.voice_client:
            if defer: await i.response.defer()
            return True
        elif i:
            if not i.user.voice or i.user.voice.channel!=self.guild.voice_client.channel:
                await i.response.send_message("join vc first",ephemeral=True)
                return True
            elif defer:await i.response.defer()

    def loadurl(self,cidx):
        if cidx>=len(self.queue): return
        c = self.queue[cidx]
        for n in range(3):
            try:
                if not c.id:
                    s = searchytm(c.fmt(),playlist=False)[0]
                    c.id = s.id
                    c.url = s.url
                    c.duration = s.duration
                elif not c.url:
                    s = extractyt(c.id)[0]
                    c.url = s.url
                    c.duration = s.duration
                break
            except Exception as e:err=r
        else:
            print(err)
            c.id = "0cVglFyHAQg" # cant be bothered to remove the song
            c.url = extractyt(c.id)[0].url
            c.duration = 7
    def loadlyrics(self):
        c=self.queue[self.cidx]
        if not c.lyrics:
            if c.spotify:
                artist = azf(c.artists[0])
                soup = bs4.BeautifulSoup(requests.get(f'{AZ}/{artist[0]}/{artist}.html').content,'lxml')
                songs = [AZ+i.get('href') for i in soup.find_all('a')if(i.get('href')or'').startswith(f'/lyrics/{artist}/')and not i.text.endswith(' Version)')and c.title in i.text]
                if songs:
                    c.lyrics = songs[0] + "\n\n" + ''.join([i.getText() for i in bs4.BeautifulSoup(requests.get(songs[0]).content,'lxml').find_all('div',attrs={'class':None,'id':None})]).strip()
                else:c.lyrics = "no lyrics found"
            else: # reverse back to spotify from youtube is inaccurateish or i just wanna push them towards using spotify
                try: c.lyrics = '\n'.join(i.text for i in youtube_transcript_api.YouTubeTranscriptApi().fetch(c.id).snippets).strip()
                except: pass
                if c.lyrics: c.lyrics = f"lyrics found on youtube subtitles\n\n" + c.lyrics
                else: c.lyrics = "no subtitles"

    async def fnext(self,i=None,channel=None,error=None):
        if await self.check(i): return
        if error: self.cidx -= 1
        if self.guild.voice_client.is_playing():
            self.guild.voice_client.stop()
            return
        else:
            self.cidx = min(self.cidx+1,len(self.queue))
        if error and 0<=self.cidx<len(self.queue):
            self.queue[self.cidx].url = None
            print(error)
        await self.frefresh(channel=channel)
        if self.cidx != len(self.queue):
            self.loadurl(self.cidx)
            src = discord.FFmpegPCMAudio(self.queue[self.cidx].url,
                before_options='-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',options='-vn')
            self.guild.voice_client.play(Source(src),
                after=lambda e: asyncio.run_coroutine_threadsafe(self.fnext(error=e),bot.loop))
            if self.paused: self.guild.voice_client.pause()
            self.loadlyrics()
            self.loadurl(self.cidx+1)
        elif self.paused:
            await self.fpause()

    async def fselect(self,i=None):
        if await self.check(i): return
        self.cidx = int(self.select.values[0])-1
        await self.fnext()

    async def frefresh(self,channel=None):
        channel = channel or self.msg.channel
        self.select.options = []
        if len(self.queue)<25 or self.cidx<=12:start = 0
        elif len(self.queue)-self.cidx<12:start = len(self.queue)-24
        else:start = self.cidx-13
        for n,i in enumerate((self.queue+[Song(title='the end')])[start:start+25]):
            self.select.add_option(label=i.fmt()[:100],default=(n+start==self.cidx),value=n+start)
        async for m in channel.history(limit=1):
            c=f"{min(len(self.queue),self.cidx+1)}/{len(self.queue)}"
            if self.cidx!=len(self.queue): c = c + f" - {self.queue[self.cidx].queued}"
            self.txtdisplay.content = c
            if m!=self.msg:
                await self.msg.delete()
                m = await channel.send(content="",view=self)
                self.msg = m
            else:
                await m.edit(content="",view=self)

    async def fclear(self,i=None):
        if await self.check(i): return
        self.queue = [i for n,i in enumerate(self.queue) if n==self.cidx]
        self.cidx = 0
        if self.queue:self.queue[0].qidx = 0
        await self.frefresh()

    async def fpause(self,i=None):
        if await self.check(i): return
        if self.cidx == len(self.queue) or self.paused:
            self.paused = False
            self.playbtn.label = "pause"
            self.playbtn.style = discord.ButtonStyle.blurple
            await self.frefresh()
            if self.cidx == len(self.queue) and self.guild.voice_client.is_playing(): self.guild.voice_client.stop()
            elif self.guild.voice_client.is_paused(): self.guild.voice_client.resume()
        else:
            self.paused = True
            self.playbtn.label = "play"
            self.playbtn.style = discord.ButtonStyle.green
            await self.frefresh()
            if self.guild.voice_client.is_playing(): self.guild.voice_client.pause()

    async def fprev(self,i=None):
        if await self.check(i): return
        self.cidx = max(0,self.cidx-(self.guild.voice_client.source and self.guild.voice_client.source.stream_time<6.7)) - 1
        await self.fnext()

    async def fleave(self,i=None):
        if await self.check(i): return
        for btn in self.btns:
            btn.disabled = True
            btn.style=discord.ButtonStyle.gray
        await self.frefresh()
        await self.guild.voice_client.disconnect()
        del servers[self.guild.id] 

    async def fshuffle(self,i=None):
        if await self.check(i): return
        self.shuffle = not self.shuffle
        if self.shuffle and self.cidx!=len(self.queue):
            self.queue = self.queue[:self.cidx+1] + random.sample(self.queue[1+self.cidx:],k=len(self.queue)-self.cidx-1)
            self.shufflebtn.label = "unshuffle"
            self.shufflebtn.style = discord.ButtonStyle.green
        elif not self.shuffle:
            try: current = self.queue[self.cidx].qidx
            except: current = len(self.queue)
            self.queue = sorted(self.queue,key=lambda i:i.qidx)
            self.shufflebtn.label = "shuffle"
            self.shufflebtn.style = discord.ButtonStyle.blurple
            try: self.cidx = self.queue.index(Song(current))
            except: pass
        await self.frefresh()
        self.loadurl(self.cidx+1)

    async def fedit(self,i=None):
        if not await self.check(i,defer=False): await i.response.send_modal(EditModal(self))

    async def flyrics(self,i=None):
        if self.cidx==len(self.queue): await i.response.defer()
        else: await i.response.send_modal(LyricsModal(self.queue[self.cidx]))

servers = {}

def extractyt(url):
    for extractor in yt_dlp.extractor.gen_extractors():
        if extractor.suitable(url) and extractor.IE_NAME.startswith('youtube'):
            with yt_dlp.YoutubeDL({'format':'bestaudio','extract_flat':'in_playlist','quiet': True,'no_warnings':True}) as ydl:
                info = ydl.extract_info(url,download=False)
                if 'entries' in info:
                    infos = [Song(n,**i)for n,i in enumerate(info['entries'])]
                    for i in infos: i.url=None
                else:
                    infos = [Song(0,**info)]
                return infos
    return []
def searchytm(search,playlist=False):
    with ytmusicapi.YTMusic() as ytm:
        x= [i for i in ytm.search(search)if (i['resultType']in['playlist','album'])==playlist]
    for n in range(5):
        try:
            if playlist: return extractyt(x[n]['playlistId'])
            else: return extractyt(x[n]['videoId']) # age restrictions and such
        except Exception as e: err=e
    else: raise err
searchfmt = lambda x:f'{x.name} - {", ".join([i.name for i in x.artists])}'

@commands.command()
async def play(ctx,*,song=''):
    if not ctx.author.voice:
        await ctx.message.add_reaction('❌')
        await ctx.send("join vc first",delete_after=5)
        return

    if ctx.guild.id not in servers: servers[ctx.guild.id] = PlayerView(ctx.guild, await ctx.send('yo'))

    channel = ctx.author.voice.channel
    if ctx.voice_client:
        await ctx.voice_client.move_to(channel)
    else:
        await channel.connect()
 
    if not song: # just summon the player
        infos = []
    else:
        infos = extractyt(song) # try yt first
        if not infos: #spotify all
            m = song.strip().split()[-2:]
            if 'youtube' in m:
                infos = searchytm(song,playlist=('playlist' in m or 'album' in m))
            else: # bad python practice cuh how else u gonna do this
                with spotify_scraper.SpotifyClient() as client:
                    if not (song.startswith('spotify:') or 'spotify.com/' in song): # search first
                        if 'playlist'in m: song=client.search(song,types=('playlist',)).playlists[0].uri
                        elif'album'in m: song=client.search(song,types=('album',)).albums[0].uri
                        else: song=client.search(song,types=('track',)).tracks[0].uri
                    a = song.replace(':','/')
                    if '/track/'in a:
                        t = client.get_track(song)
                        infos=searchytm(searchfmt(t),playlist=False)
                        infos[0].artists = [i.name for i in t.artists]
                        infos[0].title = t.name
                        infos[0].spotify = t.url
                    elif '/album/'in a: # also will search ytmusic when needed instead of now
                        t = client.get_album(song).tracks
                        infos = []
                        for n,x in enumerate(t):
                            infos.append(Song(n,title=x.name,artists=[i.name for i in x.artists],spotify=x.url))
                    elif '/playlist/'in a: # also will search ytmusic when needed instead of now
                        t = client.get_playlist(song,max_tracks=MAX_SONGS).tracks
                        infos = []
                        for n,x in enumerate(t):
                            infos.append(Song(n,title=x.track.name,artists=[i.name for i in x.track.artists],spotify=x.track.url))
                    else:infos=[]
    x=servers[ctx.guild.id]
    for i in infos:
        i.qidx += len(x.queue)
        i.queued = ctx.author.display_name
    x.queue += infos
    f = 0
    while len(x.queue)-f>MAX_SONGS and x.cidx-f: # so optimized
        f += 1
    if f or len(x.queue)>MAX_SONGS:
        x.cidx -= f
        x.queue = x.queue[f:f+MAX_SONGS]
        for i in x.queue:
            i.qidx -= f
    if len(x.queue)-len(infos) == x.cidx:
        x.cidx-=1
        await x.fnext()
    else:
        await x.frefresh(ctx.channel)

async def on_voice_state_update(member, before, after):
    if member.id==bot.user.id: return
    if not member.guild.voice_client: return
    m = member.guild.voice_client.channel.members
    if member.guild.id in servers:
        x = servers[member.guild.id]
        if all(i.bot for i in m) and not x.disconnect:
            if not x.paused:
                x.forcepaused = True
                await x.fpause()
            t = time.time()
            x.disconnect = t
            await asyncio.sleep(300)
            if member.guild.id in servers and servers[member.guild.id].disconnect==t:
                await servers[member.guild.id].fleave()
        elif x.disconnect:
            x.disconnect = 0
            if x.paused and x.forcepaused:
                await x.fpause()
            x.forcepaused = False

async def setup(b):
    global bot
    bot = b
    bot.add_command(play)
    bot.add_listener(on_voice_state_update,'on_voice_state_update')
