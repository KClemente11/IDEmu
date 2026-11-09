// Compositor Wayland mínimo do IDEmu (iDrive 8), no lugar do winston: atende o protocolo que o Ramses usa
// (wl_compositor, ivi_application, ivi_controller, wl_output). Não compõe nada: o EGL do IDEmu desenha direto no host.
typedef struct wl_display wl_display; typedef struct wl_client wl_client; typedef struct wl_resource wl_resource; typedef struct wl_interface wl_interface;
typedef unsigned u32;
extern wl_display *wl_display_create(void); extern int wl_display_add_socket(wl_display *, const char *); extern void wl_display_run(wl_display *);
extern void *wl_global_create(wl_display *, const wl_interface *, int, void *, void (*)(wl_client *, void *, u32, u32));
extern wl_resource *wl_resource_create(wl_client *, const wl_interface *, int, u32);
extern void wl_resource_set_implementation(wl_resource *, const void *, void *, void *);
extern void wl_resource_post_event(wl_resource *, u32, ...); extern void wl_resource_destroy(wl_resource *);
extern int wl_resource_get_version(wl_resource *); extern void *wl_resource_get_user_data(wl_resource *); extern void wl_resource_set_user_data(wl_resource *, void *);
extern u32 wl_display_next_serial(wl_display *); extern void *calloc(unsigned long, unsigned long); extern void free(void *);
extern int printf(const char *, ...); extern int fflush(void *); extern void *stdout;
extern int clock_gettime(int, void *);
extern const wl_interface wl_compositor_interface, wl_surface_interface, wl_region_interface, wl_callback_interface, wl_output_interface;
extern const wl_interface ivi_application_interface, ivi_surface_interface, ivi_controller_interface, ivi_controller_surface_interface, ivi_controller_layer_interface;
static void nop0(void) {}
static void des(wl_client *c, wl_resource *r) { wl_resource_destroy(r); }
typedef struct Surf { wl_resource *cb[8]; int ncb; } Surf;
static void s_frame(wl_client *c, wl_resource *r, u32 id) {
  Surf *s = wl_resource_get_user_data(r); wl_resource *cb = wl_resource_create(c, &wl_callback_interface, 1, id);
  if (s->ncb < 8) s->cb[s->ncb++] = cb;
}
static void s_commit(wl_client *c, wl_resource *r) {
  Surf *s = wl_resource_get_user_data(r); struct { long a, b; } t; clock_gettime(1, &t);
  u32 ms = (u32)(t.a * 1000 + t.b / 1000000);
  for (int i = 0; i < s->ncb; i++) { wl_resource_post_event(s->cb[i], 0, ms); wl_resource_destroy(s->cb[i]); }
  s->ncb = 0;
}
static void s_gone(wl_resource *r) { free(wl_resource_get_user_data(r)); }
static const void *surf_impl[] = { des, nop0, nop0, s_frame, nop0, nop0, s_commit, nop0, nop0, nop0, nop0 };
static const void *region_impl[] = { des, nop0, nop0 };
static void c_surface(wl_client *c, wl_resource *r, u32 id) {
  wl_resource *s = wl_resource_create(c, &wl_surface_interface, wl_resource_get_version(r), id);
  wl_resource_set_implementation(s, surf_impl, calloc(1, sizeof(Surf)), s_gone);
}
static void c_region(wl_client *c, wl_resource *r, u32 id) {
  wl_resource_set_implementation(wl_resource_create(c, &wl_region_interface, 1, id), region_impl, 0, 0);
}
static const void *comp_impl[] = { c_surface, c_region };
static void b_comp(wl_client *c, void *d, u32 v, u32 id) { wl_resource_set_implementation(wl_resource_create(c, &wl_compositor_interface, v, id), comp_impl, 0, 0); }
static const void *ivis_impl[] = { des };
static void ia_create(wl_client *c, wl_resource *r, u32 ivi, wl_resource *surf, u32 id) {
  printf("[idemuwl] ivi_surface %u\n", ivi); fflush(stdout);
  wl_resource_set_implementation(wl_resource_create(c, &ivi_surface_interface, 1, id), ivis_impl, 0, 0);
}
static const void *ia_impl[] = { ia_create };
static void b_ia(wl_client *c, void *d, u32 v, u32 id) { wl_resource_set_implementation(wl_resource_create(c, &ivi_application_interface, 1, id), ia_impl, 0, 0); }
static void x_destroy(wl_client *c, wl_resource *r, int dest) { wl_resource_destroy(r); }
static const void *ics_impl[] = { nop0, nop0, nop0, nop0, nop0, nop0, nop0, nop0, x_destroy };
static const void *icl_impl[] = { nop0, nop0, nop0, nop0, nop0, nop0, nop0, nop0, nop0, nop0, nop0, x_destroy };
static void ic_layer(wl_client *c, wl_resource *r, u32 lid, int w, int h, u32 id) { wl_resource_set_implementation(wl_resource_create(c, &ivi_controller_layer_interface, 1, id), icl_impl, 0, 0); }
static void ic_surface(wl_client *c, wl_resource *r, u32 sid, u32 id) { wl_resource_set_implementation(wl_resource_create(c, &ivi_controller_surface_interface, 1, id), ics_impl, 0, 0); }
static const void *ic_impl[] = { nop0, ic_layer, ic_surface };
static void b_ic(wl_client *c, void *d, u32 v, u32 id) { wl_resource_set_implementation(wl_resource_create(c, &ivi_controller_interface, 1, id), ic_impl, 0, 0); }
static const void *out_impl[] = { des };
static void b_out(wl_client *c, void *d, u32 v, u32 id) {
  wl_resource *r = wl_resource_create(c, &wl_output_interface, v > 2 ? 2 : v, id);
  wl_resource_set_implementation(r, out_impl, 0, 0);
  wl_resource_post_event(r, 0, 0, 0, 345, 115, 0, "BMW", "CID", 0);   // geometry
  wl_resource_post_event(r, 1, 3, 2880, 960, 60000);                  // mode: current|preferred
  if (wl_resource_get_version(r) >= 2) wl_resource_post_event(r, 2);  // done
}
int main(void) {
  wl_display *d = wl_display_create();
  if (wl_display_add_socket(d, "wayland-0")) { printf("[idemuwl] socket falhou\n"); return 1; }
  wl_global_create(d, &wl_compositor_interface, 4, 0, b_comp);
  wl_global_create(d, &ivi_application_interface, 1, 0, b_ia);
  wl_global_create(d, &ivi_controller_interface, 1, 0, b_ic);
  wl_global_create(d, &wl_output_interface, 2, 0, b_out);
  printf("[idemuwl] pronto\n"); fflush(stdout);
  wl_display_run(d);
  return 0;
}
