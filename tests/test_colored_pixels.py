"""Render the vector result and check exact old/common/new pixel colors."""
import ctypes as C
import ctypes.util
from pathlib import Path
import sys
import tempfile
import unittest

from app.rendering import colored_svg


@unittest.skipUnless(ctypes.util.find_library('rsvg-2') and ctypes.util.find_library('cairo'), 'Native SVG renderer unavailable')
class ColoredPixelTests(unittest.TestCase):
    def test_exact_colors_and_transparent_background(self):
        with tempfile.TemporaryDirectory(dir='data/test-tmp') as folder:
            folder = Path(folder)
            for side, xs in (('before',(10,40)),('after',(40,70))):
                rectangles = ''.join(f'<rect x="{x}" y="10" width="20" height="20"/>' for x in xs)
                (folder/f'{side}.svg').write_text(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50">{rectangles}</svg>')
            output = folder/'colored.svg'
            colored_svg(folder/'before.svg',folder/'after.svg',output,[0,0,100,50])
            r = C.CDLL(ctypes.util.find_library('rsvg-2'))
            c = C.CDLL(ctypes.util.find_library('cairo'))
            g = C.CDLL(ctypes.util.find_library('gobject-2.0'))
            r.rsvg_handle_new_from_file.argtypes=[C.c_char_p,C.c_void_p]; r.rsvg_handle_new_from_file.restype=C.c_void_p
            c.cairo_image_surface_create.argtypes=[C.c_int,C.c_int,C.c_int]; c.cairo_image_surface_create.restype=C.c_void_p
            c.cairo_create.argtypes=[C.c_void_p]; c.cairo_create.restype=C.c_void_p
            class Rect(C.Structure):
                _fields_=[('x',C.c_double),('y',C.c_double),('width',C.c_double),('height',C.c_double)]
            r.rsvg_handle_render_document.argtypes=[C.c_void_p,C.c_void_p,C.POINTER(Rect),C.c_void_p]
            r.rsvg_handle_render_document.restype=C.c_int
            c.cairo_surface_flush.argtypes=[C.c_void_p]
            c.cairo_image_surface_get_stride.argtypes=[C.c_void_p];c.cairo_image_surface_get_stride.restype=C.c_int
            c.cairo_image_surface_get_data.argtypes=[C.c_void_p];c.cairo_image_surface_get_data.restype=C.c_void_p
            c.cairo_destroy.argtypes=[C.c_void_p];c.cairo_surface_destroy.argtypes=[C.c_void_p];g.g_object_unref.argtypes=[C.c_void_p]
            handle=r.rsvg_handle_new_from_file(str(output).encode(),None)
            self.assertTrue(handle)
            surface=c.cairo_image_surface_create(0,1000,500)
            context=c.cairo_create(surface)
            try:
                self.assertTrue(r.rsvg_handle_render_document(handle,context,C.byref(Rect(0,0,1000,500)),None))
                c.cairo_surface_flush(surface)
                stride=c.cairo_image_surface_get_stride(surface)
                raw=C.string_at(c.cairo_image_surface_get_data(surface),stride*500)
                def pixel(x,y):
                    color=int.from_bytes(raw[y*stride+x*4:y*stride+x*4+4],sys.byteorder)
                    return ((color>>16)&255,(color>>8)&255,color&255,(color>>24)&255)
                self.assertEqual(pixel(200,200),(136,8,8,255))
                self.assertEqual(pixel(500,200),(128,127,127,255))
                self.assertEqual(pixel(800,200),(64,255,64,255))
                self.assertEqual(pixel(10,10),(0,0,0,0))
            finally:
                c.cairo_destroy(context);c.cairo_surface_destroy(surface);g.g_object_unref(handle)
