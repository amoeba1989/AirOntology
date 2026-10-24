"""Repeatable, synthetic flight paths. These are illustrations, not measured flights."""
import math
import random
from bisect import bisect_right
from functools import lru_cache
from .domain import GEOD

# Local east/north coordinates in metres, relative to one of the configured
# positions. A closed route avoids the teleport at the end of a demonstration.
ROUTES = (
    ('接近－转弯－离开', ((-650,-250),(-420,-115),(-245,-55),(-112,15),(-78,75),(-175,165),(-390,270),(-620,170))),
    ('近距离掠过－离开', ((65,-45),(100,60),(205,180),(415,255),(590,130),(430,-95),(230,-175),(100,-135))),
    ('周界巡航', ((-420,-105),(-290,145),(-105,290),(125,255),(330,65),(215,-195),(-60,-345),(-300,-275))),
    ('交叉航线－返航', ((-540,-200),(-340,-55),(-145,180),(55,90),(210,-115),(420,-160),(255,70),(75,220),(-170,-70))),
)


def _catmull(a, b, c, d, t):
    return .5 * ((2*b) + (-a+c)*t + (2*a-5*b+4*c-d)*t*t + (-a+3*b-3*c+d)*t*t*t)


@lru_cache(maxsize=256)
def _route(index):
    rng = random.Random(3419 + index * 7919)
    label, anchors = ROUTES[index % len(ROUTES)]
    angle = math.radians(rng.uniform(-27, 27))
    scale = rng.uniform(.88, 1.14)
    east = rng.uniform(-75, 75) if index > 1 else 0
    north = rng.uniform(-75, 75) if index > 1 else 0
    rotated = tuple(((x*math.cos(angle)-y*math.sin(angle))*scale+east,
                     (x*math.sin(angle)+y*math.cos(angle))*scale+north) for x,y in anchors)
    samples=[]
    for j in range(len(rotated)):
        for k in range(16):
            t=k/16
            neighbors=[rotated[(j+offset)%len(rotated)] for offset in (-1,0,1,2)]
            samples.append(tuple(_catmull(*(p[axis] for p in neighbors),t) for axis in (0,1)))
    samples.append(samples[0])
    lengths=[0.0]
    for a,b in zip(samples,samples[1:]):lengths.append(lengths[-1]+math.dist(a,b))
    # The first two routes deliberately begin at distinct distance bands.
    phase=0 if index<2 else rng.uniform(0,lengths[-1])
    return label,samples,lengths,phase,rng.uniform(5.5,9.5),rng.uniform(65,130)


def route_name(index):
    return _route(index)[0]


def route_speed(index):
    return _route(index)[4]


def _point(index,seconds):
    _,samples,lengths,phase,cruise,_=_route(index)
    # A small continuous drift breaks the perfect spline without per-frame
    # random jumps. It is not an assertion about weather or pilot intent.
    travel=(phase+seconds*cruise) % lengths[-1]
    j=min(bisect_right(lengths,travel)-1,len(samples)-2)
    blend=(travel-lengths[j])/(lengths[j+1]-lengths[j])
    x=samples[j][0]+(samples[j+1][0]-samples[j][0])*blend
    y=samples[j][1]+(samples[j+1][1]-samples[j][1])*blend
    x+=4*math.sin(seconds/23+index*.73)
    y+=3*math.sin(seconds/31+index*1.17)
    return x,y


def flight_sample(anchor,index,tick,interval):
    seconds=tick*interval
    x,y=_point(index,seconds)
    previous=_point(index,max(0,seconds-interval))
    following=_point(index,seconds+interval)
    start=previous if tick else (x,y)
    end=(x,y) if tick else following
    distance=math.dist(start,end)
    speed=distance/interval
    # GPS-like heading derived from actual displacement, never a fixed bearing.
    heading=(math.degrees(math.atan2(end[0]-start[0],end[1]-start[1]))+360)%360
    lon,lat,_=GEOD.fwd(anchor.lon,anchor.lat,math.degrees(math.atan2(x,y)),math.hypot(x,y))
    altitude=_route(index)[5]+5*math.sin(seconds/37+index)
    return lon,lat,heading,speed,altitude
