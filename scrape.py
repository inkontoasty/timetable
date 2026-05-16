import requests # this is by no means perfect its simply a lot more than good enough
from bs4 import BeautifulSoup as Soup
import pdfplumber
import re
import os
from const import *
import random

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
            if update == last_update:# and random.random()<.7:
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
    def __init__(self,start,end,course,subjects,classrooms,text): #ignores groups for now
        self.start = start
        self.end = end
        self.notified = None
        self.course = course
        self.subjects = subjects
        self.classrooms = classrooms
        self.text = text
        self.line1 = text.split('|')[-1].strip()

    def __eq__(self,other):
        return self.subjects==other.subjects and self.course==other.course and self.line1==other.line1

def gettime(s,ampm):
    s = re.findall(r'(\d\d?)\.(\d\d)(-(\d\d?)\.(\d\d))?',s)
    start = None
    end = None
    if s:
        s=s[0]
        start = (int(s[0])+12*(ampm and s[0]!='12'))*60 + int(s[1])
        if s[-1]:
            end = (int(s[-2])+12*(ampm and s[-2]!='12'))*60 + int(s[-1])
            if end<start and not ampm:
                end += 12*60
    return start,end

def make_classes(start,end,lines,classroom,uncategorized):
    lines = [lines[0],' '.join(lines[1:])]
    classrooms = [classroom]
    text = ' | '.join(lines)
    subjects = [i.replace('-',' ').split('  ')[0].split(':')[0].strip().split() for i in lines[0].split(' -')[0].split('(')[0].upper().split('/')]
    
    for n,i in enumerate(subjects): # e.g MATH1 - MATH, MATH1 ENR - MATH ENR, MATH GpA - MATH
        for m,j in enumerate(i):
            while subjects[n][m] and subjects[n][m][-1].isdigit(): subjects[n][m] = subjects[n][m][:-1].strip()
        subjects[n] = ' '.join(subjects[n])
        for k in re.findall(' GP *[A-Z]$',subjects[n]): subjects[n] = subjects[n].replace(k,'').strip()
        subjects[n] = subjects[n].strip()

    courses = {}
    if uncategorized:
        return [Class(start,end,'UNCATEGORIZED',['UNCATEGORIZED PING'],classrooms,text)]
    else:
        current = '' # tokenizer time
        course = None
        month = 'next'
        year = 'next'
        proc = lines[1].upper().replace('-','/').strip()+'/'
        #print(proc)

        for n,i in enumerate(proc):
            if i in ' /':
                if current in MONTHS:
                    month = current
                    #print('m',month)
                elif current.isdigit() and int(current) > 20:
                    year = current
                    #print('y',year)
                    if month=='next' and course in courses: # maybe 25/26 
                        month = courses[course][-1][0]
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
                    if course not in courses: courses[course]=[]
                    if (month,year) not in courses[course]: courses[course].append((month,year))
                current = ''
            else: current += i

        pmonth = pyear = ''
        prev = None 
        for course,intakes in list(courses.items())[::-1]:
            a = []
            if prev and intakes==[('next','next')]:
                courses[course] = courses[prev][:]
            else:
                for n,(month,year) in enumerate(intakes[::-1]):
                    if year=='next':
                        year = pyear
                    if month=='next':
                        month = pmonth
                    pmonth,pyear = month,year
                    if pmonth and pyear: a.append(month+year)
                if a: courses[course] = a
                else: courses[course] = [''] # so far only VUENG
            prev = course

        a = [] # ajdnasjdnasjdnakjd
        #print(courses)
        for k,v in courses.items():
            for i in v:
                a.append(Class(start,end,k+' '+i,subjects,classrooms,text))

    return a

def update(fn,ampm): # 0 am 1 pm
    doc = pdfplumber.open(os.path.join('stuff',fn))
    yo = []
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
                    rect = page.crop((midx-.001,midy-.001,midx+.001,midy+.001),strict=False).rects
                    if rect:
                        color = rect[-1]['non_stroking_color']
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
        if len([i for c,i in row if i]) < 2: continue # not a timetable row
        if re.findall(r'\d\d/\d\d/\d\d\d\d',row[0][1]): # table header row Monday\nDD/MM/YYYY
            headcol = {}
            for color,head in row[1:]:
                headcol[color] = headcol.setdefault(color,0)+1 # should be same color for all header cells
            headcol = max(headcol.keys(),key=lambda k:headcol[k]) # calculate mode color just in case
            current = [i[1] for i in row[1:]] # store times
        elif current:
            prev = None
            for n,(color,cell) in enumerate(row[1:]):
                if cell:
                    #print(n,headcol,color,cell)
                    start,end = gettime(current[n],ampm)
                    s,e = gettime(cell,ampm)
                    start = s or start
                    end = e or end
                    now = make_classes(start,end,cell.split('\n'),' | '.join(row[0][1].split('\n')),color==headcol)
                    if e:
                        yo += now
                        prev = None
                    elif not prev or now!=prev:
                        yo += now
                        prev = now
                    elif prev:
                        if s:
                            for i in prev:
                                i.end = now[0].start
                            prev = None
                        else:
                            for i in prev:
                                i.end = now[0].end
    k = 0
    while k < len(yo):
        c = yo[k]
        j = k+1
        while j < len(yo):
            c2 = yo[j]
            if c==c2 and c.start==c2.start and c.end==c2.end:
                yo[k].classrooms += c2.classrooms[:]
                yo.pop(j)
            else:
                j+=1
        k += 1
    return sorted(yo,key=lambda c:c.start)

