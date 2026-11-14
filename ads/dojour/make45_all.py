import sys, cv2, numpy as np
from PIL import Image, ImageDraw, ImageFont
F="/mnt/project-files/regulars-placards/fonts/JosefinSans-Bold.ttf"
B=lambda s: ImageFont.truetype(F,s)
BLUE,CHAR,WHITE,PALE=(74,108,134),(40,38,38),(255,255,255),(190,205,218)
SHOWS=[("nate-varrone","NATE VARRONE","NOV 18, 2026 · 7 PM"),
("jeffrey-keller","JEFFREY KELLER","NOV 19–21, 2026 · 7, 8 & 10 PM"),
("peter-revello","PETER REVELLO","DEC 4–5, 2026 · 7 & 9 PM"),
("peyton-ruddy","PEYTON RUDDY","DEC 10–12, 2026 · 7 & 9 PM"),
("matt-richards","MATT RICHARDS","DEC 18–19, 2026 · 8 PM"),
("henry-sir","HENRY SIR","JAN 15–16, 2027 · 7 & 9 PM"),
("sabrina-wu","SABRINA WU","FEB 5–6, 2027 · 7 PM"),
("james-stanley","JAMES STANLEY","FEB 19–20, 2027 · 7 PM"),
("liz-miele","LIZ MIELE","FEB 26–27, 2027 · 7 & 9 PM"),
("tyler-horvath","TYLER HORVATH","MAR 19–20, 2027 · 7 PM")]
def spaced(d,cx,y,t,f,fill,sp):
    ws=[d.textlength(c,font=f) for c in t]; x=cx-(sum(ws)+sp*(len(t)-1))/2
    for c,w in zip(t,ws): d.text((x,y),c,font=f,fill=fill); x+=w+sp
def fit(d,t,size,sp,mw):
    while size>18:
        f=B(size)
        if sum(d.textlength(c,font=f) for c in t)+sp*(len(t)-1)<=mw: return f
        size-=4
    return B(size)
heads,out=sys.argv[1],sys.argv[2]
W,H=2000,2500
for h,name,when in SHOWS:
    h_name=h
    src=Image.open(f"{heads}/{h}").convert("RGB")
    img=Image.new("RGB",(W,H),CHAR); d=ImageDraw.Draw(img)
    top=1000; ph=H-top; s=max(W/src.width,ph/src.height)
    r=src.resize((int(src.width*s),int(src.height*s)),Image.LANCZOS)
    g=cv2.cvtColor(np.array(r),cv2.COLOR_RGB2GRAY)
    cc=cv2.CascadeClassifier(cv2.data.haarcascades+'haarcascade_frontalface_default.xml')
    fs=cc.detectMultiScale(g,1.1,6,minSize=(int(r.width*0.08),)*2)
    cx,cy0=r.width//2,0
    if len(fs):
        fx,fy,fw,fh=max(fs,key=lambda f:f[2]*f[3]); cx=fx+fw//2
        cy0=max(0,min(r.height-ph, fy-int(fh*0.6)))  # face sits near the top of the photo area
        print(h_name,'face',fx,fy,fw,fh)
    x0=max(0,min(r.width-W,cx-W//2))
    r=r.crop((x0,cy0,x0+W,cy0+ph)); img.paste(r,(0,top))
    m=170
    spaced(d,W/2,300,"SISYPHUS PRESENTS",fit(d,"SISYPHUS PRESENTS",70,10,W-2*m),PALE,10)
    spaced(d,W/2,400,name,fit(d,name,230,12,W-2*m),WHITE,12)
    spaced(d,W/2,650,when,fit(d,when,90,6,W-2*m),PALE,6)
    y=810; bh=270
    d.polygon([(0,y+40),(W,y),(W,y+bh),(0,y+bh+40)],fill=BLUE)
    t1,t2="TICKETS AT","SISYPHUSBREWING.COM"
    spaced(d,W/2,y+62,t1,fit(d,t1,72,10,W-2*m),WHITE,10)
    spaced(d,W/2,y+140,t2,fit(d,t2,110,8,W-2*m),WHITE,8)
    img.save(f"{out}/{h}-dojour-4x5.jpg",quality=90)
# contact sheet
ims=[Image.open(f"{out}/{h}-dojour-4x5.jpg").resize((400,500)) for h,_,_ in SHOWS]
sheet=Image.new("RGB",(2000,1000),(255,255,255))
for i,im in enumerate(ims): sheet.paste(im,((i%5)*400,(i//5)*500))
sheet.save(f"{out}/sheet.jpg",quality=85)
