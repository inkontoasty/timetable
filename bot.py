import discord
from discord.ui import Button, View
from discord import ButtonStyle
from discord.ext import tasks,commands
from datetime import datetime
import asyncio
import traceback
import scrape
import time
from const import *

gurt = {}
last_notify = None
guild,roles,webhooks,channels=None,{},{},{}

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='.',intents=intents,max_ratelimit_timeout=30) 

async def do_role(interaction, role):
    if role in interaction.user.roles:
        await interaction.user.remove_roles(role)
        await interaction.response.send_message(content=f'{role.name} removed',ephemeral=True,delete_after=2)
    else:
        await interaction.user.add_roles(role)
        await interaction.response.send_message(content=f'{role.name} added',ephemeral=True,delete_after=2)

class RoleView(discord.ui.LayoutView):
    def __init__(self,roles):
        super().__init__(timeout=None)
        for n,role in enumerate(roles): # set row make more messages limit is 25
            if n%5 == 0:
                if n: self.add_item(row)
                row = discord.ui.ActionRow()
            button = Button(label=role.name,style=ButtonStyle([1,3,4][n%3]))
            button.callback = lambda i,r=role: do_role(i,r)
            row.add_item(button)
        self.add_item(row)

async def update_self_roles():
    r = [roles[i] for i in sorted(roles)]
    for n,i in enumerate(['choose-intake','choose-subjects']):
        c = [k for k in guild.text_channels if i==k.name][0]
        v = []
        m = []
        rolesfiltered = [x for x in r if (n==0)==(x.color!=discord.Color.default())]
        async for message in c.history(limit=200):
            if message.author == bot.user:
                m.append(message)
        m = m[::-1]
        for x in range(0,len(rolesfiltered),25):
            v.append(RoleView(rolesfiltered[x:x+25]))
        for x,view in enumerate(v):
            if x<len(m):
                await m[x].edit(view=view)
            else:
                await c.send(view=view)

class FakeTime: # testing purposes
    def __init__(self):
        self.day = 0
        self.hour = 7
        self.minute = 10
    def weekday(self): return self.day
    def next(self):
        self.minute += 20
        if self.minute>=60:
            self.minute-=60
            self.hour +=1
            if self.hour >= 19:
                self.hour = 6
                self.day = (self.day+1)%7
        return self
faketime = FakeTime()
toadd = {'webhook':set(),'channel':set(),'rsubject':set(),'rintake':set()}

@tasks.loop(count=1)
async def updater():
    updated = 0
    prev_error = None
    while True:
        try:
            await update_self_roles()
            break
        except:
            t = traceback.format_exc()
            if t!=prev_error: print(t)
            prev_error = t
            print("retrying update_self_roles")
            await asyncio.sleep(15)
    while True:
        try:
            for k,i in [(k,i) for k,v in toadd.items() for i in v]:
                if k=='webhook':
                    webhooks[i] = await channels[i].create_webhook(name='gurt')
                elif k=='channel':
                    overwrites = {
                        guild.default_role: discord.PermissionOverwrite(view_channel=False),
                        roles[i]: discord.PermissionOverwrite(view_channel=True)
                    }
                    channels[i] = await guild.create_text_channel(name=i,topic=i,overwrites=overwrites)
                    toadd['webhook'].add(i)

                elif k=='rsubject':
                    roles[i] = await guild.create_role(name=i,color=discord.Color.default())
                else:
                    roles[i] = await guild.create_role(name=i,color=discord.Color.random())
                    toadd['channel'].add(i)
                toadd[k].remove(i)
                print('add',k,i)
                updated += 1
                if updated>5 or not any(toadd.values()):
                    updated=0
                    await update_self_roles()
                await asyncio.sleep(3)
        except discord.RateLimited:
            await asyncio.sleep(30)
        except:
            t = traceback.format_exc()
            if t!=prev_error: print(t)
            prev_error = t
        await asyncio.sleep(3)

@tasks.loop(count=1)
async def timetabler():
    global last_notify,updated
    prev_error = None
    while True:
        try:
            now = datetime.now()
            #now = faketime.next()

            if not (6<=now.hour<=20 and 0<=now.weekday()<=4): return
            day = WEEKDAYS[now.weekday()]
            print(day,now.hour,now.minute)

            t = f"({'AP'[now.hour>=12]}M)" # 12-1 is still am apparently
            fn = scrape.download(day,t)
            print(t,fn)
            if fn:
                for k,v in scrape.update(fn).items():
                    print(k,len(v))
                    gurt[k] = v
            
            for duration in gurt:
                minutes = ((int(duration[:2]) + 12*('PM' in t))%24)*60 + int(duration[3:5])
                if last_notify!=minutes and 0 < (minutes - now.hour*60 - now.minute) <= 20:
                    while gurt[duration]:
                        c = gurt[duration][-1]
                        for intake in c.courses:
                            if intake not in roles:
                                toadd['rintake'].add(intake)
                        for subject in c.subjects:
                            if subject not in roles:
                                toadd['rsubject'].add(subject)
                        for intake in c.courses:
                            if intake not in channels and intake in roles:
                                toadd['channel'].add(intake)
                            if intake not in webhooks and intake in channels:
                                toadd['webhook'].add(intake)
                            if intake in webhooks:
                                try:
                                    p = ' '.join(f'<@&{roles[subject].id}>' for subject in c.subjects)
                                except: p = ' '.join(subject for subject in c.subjects)
                                try:
                                    await webhooks[intake].send(f'{p} {" / ".join(c.classrooms)} | {c.text}')
                                except discord.RateLimited:
                                    await channels[intake].send(f'{p} {" / ".join(c.classrooms)} | {c.text}')
                                print('"'+intake+'"',' '.join(f'@{subject}'for subject in c.subjects),c.classrooms,'"'+c.text+'"')
                                await asyncio.sleep(3)
                        gurt[duration].pop()
                    last_notify = minutes
                    break
            await asyncio.sleep(REPEAT_TIME-(time.time()+REPEAT_TIME)%REPEAT_TIME)
        except:
            t = traceback.format_exc()
            if t != prev_error: print(t)
            prev_error = t
            print("retrying in 15")
            await asyncio.sleep(15)

@bot.event
async def on_ready():
    global guild,channels,roles,webhooks
    print("ready")
    while True:
        try:
            guild = bot.get_guild(GUILD) or await bot.fetch_guild(GUILD)
            channels = {i.topic:i for i in guild.text_channels}
            roles = {i.name:i for i in await guild.fetch_roles() if i.name.isupper()}
            webhooks = {i.channel.topic:i for i in await guild.webhooks()}
            if not timetabler.is_running(): timetabler.start()
            if not updater.is_running(): updater.start()
            break
        except:
            print("retrying start bot in 30")
            await asyncio.sleep(30)

@bot.event
async def on_resumed():
    print("resumed")
    if not timetabler.is_running(): timetabler.start()
    if not updater.is_running(): updater.start()

@bot.command()
async def yo(ctx):
    if ctx.author.id == 736788057734381629:
        await ctx.message.delete()
        r = [i for i in ctx.guild.roles if i.name=='yo'][0]
        if r in ctx.author.roles:
            await ctx.author.remove_roles(r)
        else:
            await ctx.author.add_roles(r)

if __name__ == '__main__': bot.run(TOKEN)
