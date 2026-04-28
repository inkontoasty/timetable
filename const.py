
try:
    exec(open('.secret','r').read())
except FileNotFoundError:
    open('.secret','w').write('''
USR = "26020495" # ilearn user id
PWD = "ILEARN_PASSWORD"
TOKEN = "DISCORD_BOT_TOKEN"
GUILD = 1496867465945157632 # server id
    ''')
    raise Exception(".secret file created")
URL = 'https://ilearn.sunway.edu.my/'
LOGIN = URL+'login/index.php'
HEAD = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) Gecko/20100101 Firefox/149.0'}
MONTHS = 'JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC'.split()
WEEKDAYS = 'MON TUE WED THU FRI'.split()
REPEAT_TIME = 600 #seconds
