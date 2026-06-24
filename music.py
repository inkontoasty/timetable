import discord
from discord.ext import commands
import yt_dlp,asyncio,random,ytmusicapi,spotify_scraper,time

# pro queue modal with 2 selects and pages???
bot = None

class Song:
    def __init__(self,qidx=-1,**kwargs):
        self.id = kwargs.get('id')
        self.title = kwargs.get('title','a')
        self.url = kwargs.get('url')
        self.queued = kwargs.get('queued')
        self.qidx = qidx # unique i hope
    def __eq__(self,other): return self.qidx==other.qidx
    def __repr__(self): return f'{self.qidx} {self.title} {self.id} {self.url}'

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
        self.editbtn = discord.ui.Button(label='edit',style=discord.ButtonStyle.blurple)
        self.clearbtn = discord.ui.Button(label='clear',style=discord.ButtonStyle.red)
        self.leavebtn = discord.ui.Button(label='leave',style=discord.ButtonStyle.red)
        #row.add_item(self.editbtn)
        row.add_item(self.clearbtn)
        row.add_item(self.leavebtn)
        self.add_item(row)

        self.nextbtn.callback = self.fnext
        self.clearbtn.callback = self.fclear
        self.playbtn.callback = self.fpause
        self.prevbtn.callback = self.fprev
        self.leavebtn.callback = self.fleave
        self.shufflebtn.callback = self.fshuffle
        self.select.callback = self.fselect
        #self.editbtn.callback = self.fedit

    async def check(self,i):
        if not self.guild.voice_client:
            await i.response.defer()
            return True
        if i:
            if not i.user.voice or i.user.voice.channel!=self.guild.voice_client.channel:
                await i.response.send_message("join vc first",ephemeral=True)
                return True
            else:await i.response.defer()

    def loadurl(self,cidx):
        if cidx>=len(self.queue): return
        c = self.queue[cidx]
        if not c.id:
            try:
                s = searchytm(c.title,playlist=False)[0]
                c.id = s.id
                c.url = s.url
            except IndexError: # search fails
                c.id = "rGTGdvy409A" # cant be bothered to remove the song
                c.url = extractyt(c.id)[0].url
        elif not c.url: c.url = extractyt(c.id)[0].url

    async def fnext(self,i=None,channel=None):
        if await self.check(i): return
        if self.guild.voice_client.is_playing():
            self.guild.voice_client.stop()
            return
        else:
            self.cidx = min(self.cidx+1,len(self.queue))
        await self.frefresh(channel=channel)
        if self.cidx != len(self.queue):
            self.loadurl(self.cidx)
            src = discord.FFmpegPCMAudio(self.queue[self.cidx].url,
                before_options='-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',options='-vn')
            self.guild.voice_client.play(Source(src),
                after=lambda e: asyncio.run_coroutine_threadsafe(self.fnext(),bot.loop))
            if self.paused: self.guild.voice_client.pause()
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
            self.select.add_option(label=i.title[:100],default=(n+start==self.cidx),value=n+start)
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
        #self.cidx = max(0,self.cidx-1) - 1
        self.cidx = max(0,self.cidx-(self.guild.voice_client.source and self.guild.voice_client.source.stream_time<6.7)) - 1
        await self.fnext()

    async def fleave(self,i=None):
        if await self.check(i): return
        for btn in [self.playbtn,self.shufflebtn,self.leavebtn,self.nextbtn,self.prevbtn,self.clearbtn]: btn.style=discord.ButtonStyle.gray
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
    with ytmusicapi.YTMusic() as ytm:x= [i for i in ytm.search(search)if (i['resultType']in['playlist','album'])==playlist]
    if playlist: return extractyt(x[0]['playlistId'])
    else: return extractyt(x[0]['videoId'])
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
    elif song.startswith('spotify:') or 'spotify.com/' in song:
        a = song.replace(':','/')
        with spotify_scraper.SpotifyClient() as client: #all will lead to getting stream url when needed
            if '/album/'in a: infos=searchytm(searchfmt(client.get_album(song)),playlist=True)
            elif '/track/'in a: infos=searchytm(searchfmt(client.get_track(song)),playlist=False)
            elif '/playlist/'in a: # also will search ytmusic when needed instead of now
                infos = [Song(n,title=searchfmt(i.track)) for n,i in enumerate(client.get_playlist(song,max_tracks=10000).tracks)]
            else:infos=[]
    else:
        infos = extractyt(song)
    if not infos:
        infos = searchytm(song,playlist=song.lower().strip().split()[-1]in['playlist','album'])

    x=servers[ctx.guild.id]
    for i in infos:
        i.qidx += len(x.queue)
        i.queued = ctx.author.display_name
    if len(x.queue) == x.cidx:
        x.queue += infos
        x.cidx-=1
        await x.fnext()
    else:
        x.queue += infos
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
            x.forcepaused = False
            if x.paused and x.forcepaused:
                await x.fpause()

async def setup(b):
    global bot
    bot = b
    bot.add_command(play)
    bot.add_listener(on_voice_state_update,'on_voice_state_update')
