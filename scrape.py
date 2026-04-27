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
    a = [i for i in soup.find_all('a') if 'classroom allocation' in i.text.lower()][0] # can save one request but nah
    r = session.get(a['href'])
    for a in Soup(r.content,features='lxml').find_all('a'):
        text = a.text.upper()
        if day in text and t in text:
            update = day+t+re.findall(r'UPDATED \d\d/\d\d \d\d?.\d\d[A,P]M',text.upper().replace('  ',''))[0]
            print(update,last_update)
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
    def __init__(self,lines,classroom): # hard part
        self.lines = lines
        self.classrooms = [classroom]
        self.text = ' | '.join(lines)
        self.subjects = [i.replace('-',' ').strip() for i in lines[0].split(' -')[0].split('(')[0].upper().split('/')]
        self.courses = {}
        if len(lines)==1:
            self.courses = ['UNCATEGORIZED']
            self.subjects = ['UNCATEGORIZED PING']
        else:
            current = '' # tokenizer time
            course = None
            month = 'next'
            year = 'next'
            proc = self.lines[1].upper().split('-')[0].strip()+'/'
            #print(proc)
            for n,i in enumerate(proc):
                if i in ' /':
                    if current in MONTHS:
                        month = current
                        #print('m',month)
                        current = ''
                    elif current.isdigit() and int(current) > 20:
                        year = current
                        #print('y',year)
                        if month=='next' and course in self.courses: # maybe 25/26 
                            month = self.courses[course][-1][0]
                        current = ''
                    elif any(f:=re.findall(r'(Y\d)?(S\d)?',current)[0]): # VU uses Y1S2, Y3S1 etc 
                        if f[1]: year = f[1] # counter intuitive but since month goes first and Y1 goes first
                        if f[0]: month = f[0]
                        current = ''
                    elif current.strip():
                        course = current
                        #print('c',course)
                        current = ''
                        month = 'next'
                        year = 'next'
                    if i == '/' and course:
                        #print('add',course,month,year)
                        if course not in self.courses: self.courses[course]=[]
                        self.courses[course].append((month,year))
                else: current += i

            pmonth = pyear = ''
            for course,intakes in list(self.courses.items())[::-1]:
                a = []
                for n,(month,year) in enumerate(intakes[::-1]):
                    if year=='next':
                        year = pyear
                    if month=='next':
                        month = pmonth
                    pmonth,pyear = month,year
                    if pmonth and pyear: a.append(month+year)
                if a: self.courses[course] = a
                elif len(self.lines[0].split(' -'))>=2: self.courses[course] = [''] # so far only VUENG
                else:del self.courses[course]

            a = [] # ajdnasjdnasjdnakjd
            #print(self.courses)
            for k,v in self.courses.items():
                for i in v: a.append(k+' '+i)
            if not a:
                a.append('UNCATEGORIZED')
                self.subjects = ['UNCATEGORIZED PING']
            self.courses = [i.strip() for i in a]

        for n,i in enumerate(self.subjects):
            while self.subjects[n][-1].isdigit(): self.subjects[n] = self.subjects[n][:-1].strip()
            for k in re.findall(' GP *[A-Z]$',i): self.subjects[n] = self.subjects[n].replace(k,'').strip() # what if gpa is a subject gng 

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
                        r.append('')
                        continue
                    x0,y0,x1,y1=cell
                    s = []
                    currenty = 0
                    currentx = 0
                    for char in page.within_bbox(cell,strict=False).chars:
                        if char['upright']:
                            if currenty -char['y0'] > char['height']/3:
                                s.append('\n')
                            elif char['x0'] - currentx > char['width']*9/32:
                                s.append(' ')
                            s.append(char['text'])
                            currentx = char['x1']
                            currenty = char['y0']
                    r.append(''.join(s).strip())
                rows.append(r)
    current = []
    for row in rows:
        #print(row)
        if 'BLOCK' in row[0].upper():
            current = []
            continue
        if re.findall(r'\d\d/\d\d/\d\d\d\d',row[0]):
            for head in row[1:]:
                if head not in yo: yo[head] = []
            current = row[1:]
        elif current:
            for n,cell in enumerate(row[1:]):
                if cell:
                    yo[current[n]].append(Class(cell.split('\n'),' | '.join(row[0].split('\n'))))
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
                    l[n][1][k].classrooms += c2.classrooms[:]
                    l[n][1].remove(c2)
            k += 1
    return yo

