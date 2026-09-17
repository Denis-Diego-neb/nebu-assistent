"""Seletor HSV compacto; envia a cor somente ao soltar o mouse."""
import colorsys
import math
import tkinter as tk
from PIL import Image, ImageTk


class ColorWheel(tk.Canvas):
    def __init__(self, parent, command, size=200, background=None):
        background = background or str(parent.cget('bg'))
        super().__init__(parent, width=size, height=size, bg=background, highlightthickness=0, cursor='crosshair')
        self.command, self.size = command, size
        self.color = '#FFFFFF'
        image = Image.new('RGBA', (size, size))
        pixels = image.load()
        center = size/2
        radius = center-3
        for y in range(size):
            for x in range(size):
                dx, dy = x-center, y-center
                saturation = math.hypot(dx, dy)/radius
                if saturation <= 1:
                    hue = (math.atan2(dy, dx)/(2*math.pi)) % 1
                    pixels[x, y] = tuple(round(v*255) for v in colorsys.hsv_to_rgb(hue, saturation, 1)) + (255,)
        self.image = ImageTk.PhotoImage(image)
        self.create_image(0, 0, anchor='nw', image=self.image)
        self.marker = self.create_oval(center-5, center-5, center+5, center+5, outline='white', width=2)
        self.bind('<Button-1>', self.select)
        self.bind('<B1-Motion>', self.select)
        self.bind('<ButtonRelease-1>', self.commit)

    def select(self, event):
        center, radius = self.size/2, self.size/2-3
        dx, dy = event.x-center, event.y-center
        distance = math.hypot(dx, dy)
        saturation = min(1, distance/radius)
        hue = (math.atan2(dy, dx)/(2*math.pi)) % 1
        self.color = '#%02X%02X%02X' % tuple(round(v*255) for v in colorsys.hsv_to_rgb(hue, saturation, 1))
        factor = min(1, radius/max(distance, 1))
        x, y = center+dx*factor, center+dy*factor
        self.coords(self.marker, x-5, y-5, x+5, y+5)

    def commit(self, event):
        self.select(event)
        self.command(self.color)
