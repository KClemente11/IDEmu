/* Decode PNG/JPEG map tiles into tightly packed premultiplied RGBA. */
#ifdef __APPLE__
#include <ApplicationServices/ApplicationServices.h>
#include <stdlib.h>
#include <string.h>
unsigned char *pngload(const char *path,int *w,int *h){
  CFStringRef s=CFStringCreateWithCString(0,path,kCFStringEncodingUTF8); if(!s) return 0;
  CFURLRef u=CFURLCreateWithFileSystemPath(0,s,kCFURLPOSIXPathStyle,0); CFRelease(s); if(!u) return 0;
  CGImageSourceRef src=CGImageSourceCreateWithURL(u,0); CFRelease(u); if(!src) return 0;
  CGImageRef img=CGImageSourceCreateImageAtIndex(src,0,0); CFRelease(src); if(!img) return 0;
  int W=(int)CGImageGetWidth(img),H=(int)CGImageGetHeight(img);
  unsigned char *px=calloc(1,(size_t)W*H*4);
  CGColorSpaceRef cs=CGColorSpaceCreateDeviceRGB();
  CGContextRef c=px?CGBitmapContextCreate(px,W,H,8,(size_t)W*4,cs,kCGImageAlphaPremultipliedLast):0;
  if(c){ CGContextDrawImage(c,CGRectMake(0,0,W,H),img); CGContextRelease(c); } else { free(px); px=0; }
  CGColorSpaceRelease(cs); CGImageRelease(img); *w=W; *h=H; return px; }
#else
#include <gdk-pixbuf/gdk-pixbuf.h>
#include <stdlib.h>

unsigned char *pngload(const char *path, int *w, int *h){
  GdkPixbuf *image = gdk_pixbuf_new_from_file(path, NULL);
  if(!image) return NULL;
  *w = gdk_pixbuf_get_width(image);
  *h = gdk_pixbuf_get_height(image);
  int stride = gdk_pixbuf_get_rowstride(image);
  int channels = gdk_pixbuf_get_n_channels(image);
  const unsigned char *pixels = gdk_pixbuf_read_pixels(image);
  unsigned char *rgba = calloc((size_t)*w * *h, 4);
  if(rgba){
    for(int y = 0; y < *h; y++){
      const unsigned char *src = pixels + (size_t)y * stride;
      unsigned char *dst = rgba + (size_t)y * *w * 4;
      for(int x = 0; x < *w; x++, src += channels, dst += 4){
        unsigned int alpha = channels == 4 ? src[3] : 255;
        for(int c = 0; c < 3; c++) dst[c] = (src[c] * alpha + 127) / 255;
        dst[3] = alpha;
      }
    }
  }
  g_object_unref(image);
  return rgba;
}
#endif
