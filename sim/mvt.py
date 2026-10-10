"""Decodificador mínimo de Mapbox Vector Tiles (protobuf) sin dependencias externas.

Solo lo necesario para leer polígonos (edificios, bosques) y sus atributos.
"""


def _varint(b, i):
    r = 0
    s = 0
    while True:
        c = b[i]
        i += 1
        r |= (c & 0x7F) << s
        if c < 0x80:
            return r, i
        s += 7


def _fields(b):
    """Itera (número_de_campo, tipo, valor) de un mensaje protobuf."""
    i = 0
    n = len(b)
    while i < n:
        key, i = _varint(b, i)
        f, t = key >> 3, key & 7
        if t == 0:
            v, i = _varint(b, i)
        elif t == 2:
            ln, i = _varint(b, i)
            v = b[i:i + ln]
            i += ln
        elif t == 1:
            v = b[i:i + 8]
            i += 8
        elif t == 5:
            v = b[i:i + 4]
            i += 4
        else:
            raise ValueError("tipo protobuf no soportado")
        yield f, t, v


def _packed(b):
    out = []
    i = 0
    while i < len(b):
        v, i = _varint(b, i)
        out.append(v)
    return out


def _zz(n):
    return (n >> 1) ^ -(n & 1)


def _value(b):
    import struct
    for f, t, v in _fields(b):
        if f == 1:
            return bytes(v).decode("utf-8", "replace")
        if f == 2:
            return struct.unpack("<f", bytes(v))[0]
        if f == 3:
            return struct.unpack("<d", bytes(v))[0]
        if f in (4, 5):
            return v
        if f == 6:
            return _zz(v)
        if f == 7:
            return bool(v)
    return None


def _geometry(cmds):
    """Devuelve lista de anillos [(x, y), ...] en coordenadas de la tesela."""
    rings = []
    cur = []
    x = y = 0
    i = 0
    while i < len(cmds):
        c = cmds[i]
        i += 1
        cid, cnt = c & 7, c >> 3
        if cid == 1:          # MoveTo
            for _ in range(cnt):
                x += _zz(cmds[i])
                y += _zz(cmds[i + 1])
                i += 2
                if cur:
                    rings.append(cur)
                cur = [(x, y)]
        elif cid == 2:        # LineTo
            for _ in range(cnt):
                x += _zz(cmds[i])
                y += _zz(cmds[i + 1])
                i += 2
                cur.append((x, y))
        elif cid == 7:        # ClosePath
            if cur:
                rings.append(cur)
            cur = []
    if cur:
        rings.append(cur)
    return rings


def decode(data, layers=None):
    """dict capa -> lista de (tipo_geom, anillos, atributos, extent)."""
    out = {}
    if bytes(data[:2]) == bytes([0x1F, 0x8B]):
        import gzip
        data = gzip.decompress(bytes(data))
    mv = memoryview(data)
    for f, t, v in _fields(mv):
        if f != 3:
            continue
        name = None
        extent = 4096
        keys, vals, feats = [], [], []
        for lf, lt, lv in _fields(v):
            if lf == 1:
                name = bytes(lv).decode()
            elif lf == 2:
                feats.append(lv)
            elif lf == 3:
                keys.append(bytes(lv).decode())
            elif lf == 4:
                vals.append(lv)
            elif lf == 5:
                extent = lv
        if layers and name not in layers:
            continue
        vals = [_value(x) for x in vals]
        res = []
        for fb in feats:
            gtype = 0
            tags = []
            geom = []
            for ff, ft, fv in _fields(fb):
                if ff == 2:
                    tags = _packed(fv)
                elif ff == 3:
                    gtype = fv
                elif ff == 4:
                    geom = _packed(fv)
            attrs = {keys[tags[k]]: vals[tags[k + 1]] for k in range(0, len(tags) - 1, 2)}
            res.append((gtype, _geometry(geom), attrs, extent))
        out[name] = out.get(name, []) + res
    return out
