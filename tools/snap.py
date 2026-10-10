"""Genera capturas de prueba del renderizador (para desarrollo)."""
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SDL_VIDEO_WINDOW_POS", "40,40")
import moderngl
import numpy as np
import pygame

from render.camera import Camera
from render.renderer import Renderer
from sim.world import World

out = sys.argv[1] if len(sys.argv) > 1 else "."
W, H = 1280, 720
pygame.init()
pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 3)
pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 3)
pygame.display.gl_set_attribute(pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_CORE)
pygame.display.gl_set_attribute(pygame.GL_DEPTH_SIZE, 24)
pygame.display.set_mode((W, H), pygame.OPENGL | pygame.DOUBLEBUF)
ctx = moderngl.create_context()
print(ctx.info["GL_RENDERER"], ctx.info["GL_VERSION"])
t0 = time.time()
LOC = os.environ.get("LOC")
if LOC:
    from sim import geo
    world = World(location=geo.build_location(LOC, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "datos")))
else:
    world = World()
print("mundo", time.time() - t0)
AC = os.environ.get("AC")
if AC:
    world.set_aircraft(AC)
t0 = time.time()
r = Renderer(ctx, world, (W, H), progress=print)
print("renderer", time.time() - t0)
cam = Camera()
overlay = pygame.Surface((W, H), pygame.SRCALPHA)


def shot(name, n=3):
    for _ in range(n):
        cam.update(0.016, world)
        t = time.time()
        r.render(cam, (0, 0, W, H))
        r.draw_overlay(overlay)
        ctx.finish()
        dt = time.time() - t
        pygame.display.flip()
    data = ctx.screen.read(components=3)
    img = pygame.image.frombytes(data, (W, H), "RGB", True)
    pygame.image.save(img, os.path.join(out, name + ".png"))
    print(name, f"{dt*1000:.1f} ms")


cases = sys.argv[2].split(",") if len(sys.argv) > 2 else ["runway", "chase", "air", "final", "orbit", "dusk", "night", "overcast", "tower"]
for c in cases:
    world.weather.hour = 11.0
    world.weather.cloud_cover = 0.35
    if c == "runway":
        world.reposition("pista36"); cam.set_mode("cabina")
    elif c == "chase":
        world.reposition("pista36"); cam.set_mode("exterior")
    elif c == "air":
        world.reposition("crucero"); cam.set_mode("cabina")
    elif c == "final":
        world.reposition("final3"); cam.set_mode("cabina")
    elif c == "orbit":
        world.reposition("viento_cola"); cam.set_mode("libre"); cam.orbit_dist = 18
    elif c == "orbit2":
        world.reposition("viento_cola"); cam.set_mode("libre"); cam.orbit_dist = 16; cam.orbit_yaw = 2.3; cam.orbit_pitch = 0.35
    elif c == "ground":
        world.reposition("pista"); cam.set_mode("libre"); cam.orbit_dist = 14; cam.orbit_yaw = 2.5; cam.orbit_pitch = 0.15
    elif c == "dusk":
        world.weather.hour = 18.6; world.reposition("final3"); cam.set_mode("exterior")
    elif c == "night":
        world.weather.hour = 22.0; world.reposition("final3"); cam.set_mode("cabina")
    elif c == "night_rwy":
        world.weather.hour = 22.0; world.reposition("pista36"); cam.set_mode("cabina")
    elif c == "overcast":
        world.weather.cloud_cover = 0.95; world.weather.cloud_base_ft = 1800; world.weather.cloud_top_ft = 3500
        world.reposition("crucero"); cam.set_mode("exterior")
    elif c == "tower":
        world.reposition("final3"); cam.set_mode("torre")
    shot(c)
pygame.quit()
