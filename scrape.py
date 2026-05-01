import requests
from bs4 import BeautifulSoup as Soup
import pdfplumber
import re
import os
from const import *

last_update = None
session = requests.Session()
try: os.mkdir('stuff')
except FileExistsError: pass

def download(day,t): # easy part
    global last_update,session
    try:
        r = session.get(URL)
    except:
        session = requests.Session()
        r = session.get(URL)
    if b'<title>log in' in r.content.lower():
        r = session.get(LOGIN)
        payload = {i.get('name'):i.get('value') for i in Soup(r.content,features='lxml').find_all('input')}
        payload['username'] = USR
        payload['password'] = PWD
        if None in payload: del payload[None]
        r = session.post(LOGIN,data=payload,headers=HEAD)
    soup = Soup(r.content,features='lxml')
    a = [i for i in soup.find_all('a') if 'classroom allocation' in i.text.lower()][0]
    r = session.get(a['href'])
    for a in Soup(r.content,features='lxml').find_all('a'):
        text = a.text.upper()
        if day in text and t in text:
            update = day+t+re.findall(r'UPDATED \d\d/\d\d \d\d?.\d\d[A,P]M',text.upper().replace('  ',''))[0]
            if update == last_update:
                return
            last_update = update
            break
    else:
        return

    r = session.get(a['href'])
    fn = f"{day}_{t[1:-1]}.pdf"
    with open(os.path.join('stuff',fn),"wb") as f:
        f.write(r.content)
    return fn

class Class: # whos gonna stop me
    def __init__(self,lines,classroom,uncat=False): #ignores groups for now
        self.lines = [lines[0],' '.join(lines[1:])]
        self.classrooms = [classroom]
        self.text = ' | '.join(lines)
        self.subjects = [i.replace('-',' ').split('  ')[0].strip().split() for i in lines[0].split(' -')[0].split('(')[0].upper().split('/')]
        for n,i in enumerate(self.subjects):
            for m,j in enumerate(i):
                while self.subjects[n][m] and self.subjects[n][m][-1].isdigit(): self.subjects[n][m] = self.subjects[n][m][:-1].strip()
            self.subjects[n] = ' '.join(self.subjects[n])
            for k in re.findall(' GP *[A-Z]$',self.subjects[n]): self.subjects[n] = self.subjects[n].replace(k,'').strip()

        self.courses = {}
        if uncat:
            self.courses = ['UNCATEGORIZED']
            self.subjects = ['UNCATEGORIZED PING']
        else:
            current = '' # tokenizer time
            course = None
            month = 'next'
            year = 'next'
            proc = self.lines[1].upper().replace('-','/').strip()+'/'
            #print(proc)

            for n,i in enumerate(proc):
                if i in ' /':
                    if current in MONTHS:
                        month = current
                        #print('m',month)
                    elif current.isdigit() and int(current) > 20:
                        year = current
                        #print('y',year)
                        if month=='next' and course in self.courses: # maybe 25/26 
                            month = self.courses[course][-1][0]
                    elif any(f:=re.findall(r'(Y\d)?(S\d)?',current)[0]): # VU uses Y1S2, Y3S1 etc 
                        if f[1]: year = f[1] # counter intuitive but since month goes first and Y1 goes first
                        if f[0]: month = f[0]
                    elif len(current.strip())>1: # groups are one letter 1/2/3/A/B
                        course = current
                        #print('c',course)
                        month = 'next'
                        year = 'next'
                    if i == '/' and course:
                        #print('add',course,month,year)
                        if course not in self.courses: self.courses[course]=[]
                        if (month,year) not in self.courses[course]: self.courses[course].append((month,year))
                    current = ''
                else: current += i

            pmonth = pyear = ''
            prev = None 
            for course,intakes in list(self.courses.items())[::-1]:
                a = []
                if prev and intakes==[('next','next')]:
                    self.courses[course] = self.courses[prev][:]
                else:
                    for n,(month,year) in enumerate(intakes[::-1]):
                        if year=='next':
                            year = pyear
                        if month=='next':
                            month = pmonth
                        pmonth,pyear = month,year
                        if pmonth and pyear: a.append(month+year)
                    if a: self.courses[course] = a
                    else: self.courses[course] = [''] # so far only VUENG
                prev = course

            a = [] # ajdnasjdnasjdnakjd
            #print(self.courses)
            for k,v in self.courses.items():
                for i in v: a.append(k+' '+i)
            self.courses = [i.strip() for i in a]

    def __eq__(self,other):
        return self.classrooms==other.classrooms and self.subjects==other.subjects and self.courses==other.courses

def update(fn):
    doc = pdfplumber.open(os.path.join('stuff',fn))
    yo = {}
    rows = []
    for page in doc.pages:
        for table in page.find_tables():
            for row in table.rows:
                r = []
                for cell in row.cells:
                    if not cell:
                        r.append(((1.0,1.0,1.0),''))
                        continue
                    s = []
                    currenty = 0
                    currentx = 0
                    midx,midy = (cell[2]+cell[0])/2,(cell[3]+cell[1])/2
                    best = float('inf')
                    rect = None
                    for i in page.crop(cell,strict=False).rects:
                        dist = round((midx-(i['x0']+i['x1'])/2)**2 + (midy-(i['top']+i['bottom'])/2)**2,2)
                        if dist <= best:
                            best = dist
                            rect = i
                    if rect:
                        color = rect['non_stroking_color']
                        if type(color) != tuple:
                            color = (color,color,color)
                        color = (round(color[0],2),round(color[1],2),round(color[2],2))
                    else: color = (1.0,1.0,1.0)
                    for char in page.within_bbox(cell,strict=False).chars:
                        if char['upright']:
                            if currenty -char['y0'] > char['height']/3:
                                s.append('\n')
                            elif char['x0'] - currentx > char['size']*9/16/3:
                                s.append(' ')
                            s.append(char['text'])
                            currentx = char['x0'] + char['width']*(1-char['matrix'][2])
                            currenty = char['y0']
                    r.append((color,''.join(s).strip()))
                rows.append(r)
    #return rows
    current = []
    for row in rows:
        #print(row)
        if len([i for c,i in row if i]) < 2: continue
        if re.findall(r'\d\d/\d\d/\d\d\d\d',row[0][1]):
            headcol = {}
            for color,head in row[1:]:
                headcol[color] = headcol.setdefault(color,0)+1
                if head not in yo: yo[head] = []
            headcol = max(headcol.keys(),key=lambda k:headcol[k])
            current = [i[1] for i in row[1:]]
        elif current:
            for n,(color,cell) in enumerate(row[1:]):
                if cell:
                    #print(n,headcol,color,cell)
                    yo[current[n]].append(Class(cell.split('\n'),' | '.join(row[0][1].split('\n')),color==headcol))
    l=sorted(yo.items(),key=lambda x:x[0],reverse=True)
    for n,(duration,classes) in enumerate(l[:-1]):
        for c in classes[:]:
            if c in l[n+1][1]:
                yo[duration].remove(c)
        k = 0
        while k < len(l[n][1]):
            c = l[n][1][k]
            for c2 in l[n][1][k+1:][:]:
                if c2.subjects == c.subjects and c2.text.split('|')[-1].strip()==c.text.split('|')[-1].strip():
                    yo[duration][k].classrooms += c2.classrooms[:]
                    yo[duration].remove(c2)
            k += 1
    return yo

