import struct,zlib,sys,time
d=open('/tmp/idemu-id7/frame.rgba','rb').read()
w,h,seq=struct.unpack_from('<iii',d,0); print('frame',w,h,'seq',seq)
px=d[64:64+w*h*4]
raw=b''.join(b'\x00'+px[y*w*4:(y+1)*w*4] for y in range(h))
def ch(t,b): c=struct.pack('>I',len(b))+t+b; return c+struct.pack('>I',zlib.crc32(t+b)&0xffffffff)
open(sys.argv[1],'wb').write(b'\x89PNG\r\n\x1a\n'+ch(b'IHDR',struct.pack('>IIBBBBB',w,h,8,6,0,0,0))+ch(b'IDAT',zlib.compress(raw,3))+ch(b'IEND',b''))
nz=sum(1 for i in range(0,len(px),4*997) if px[i:i+3]!=b'\0\0\0'); print('amostras não pretas',nz)
