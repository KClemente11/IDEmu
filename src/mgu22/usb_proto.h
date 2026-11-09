// Protocolo do pen drive virtual do iDrive 8 (host -> guest, canal de papel 3, anel B).
// Cada mensagem: cabeçalho fixo de 24 bytes, depois `namelen` bytes de nome e, para USB_FILE, `size` bytes de dados.
#ifndef IDEMU_USB_PROTO_H
#define IDEMU_USB_PROTO_H
#define USB_MAGIC 0x31425355u  // "USB1"
enum { USB_BEGIN = 1, USB_FILE = 2, USB_DIR = 3, USB_END = 4, USB_EJECT = 5 };
typedef struct usb_msg {
  unsigned magic, op;
  unsigned long long size;  // BEGIN: bytes previstos; FILE: bytes de dados
  unsigned namelen, rsvd;   // BEGIN: nome = rótulo; FILE/DIR: caminho relativo
} usb_msg;
#define USB_ROLE 3
#endif
