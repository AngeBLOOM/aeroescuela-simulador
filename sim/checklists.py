"""Listas de verificación normales y de emergencia (basadas en los manuales POH/AFM).

Cada elemento: (acción, valor esperado, función de comprobación automática o None).
Los elementos sin función se marcan a mano con un clic.
"""
from .mathx import FT


def _eng(w):
    return w.ac.sys.engines


def lists_for(world):
    t = world.ac.t
    s = world.ac.sys
    e = s.engine
    ac = world.ac
    fadec = t.fadec
    twin = s.twin
    L = []

    pre = [("Freno de estacionamiento", "PUESTO", lambda w: s.parking_brake),
           ("Asientos y cinturones", "AJUSTADOS", None),
           ("Interruptores eléctricos", "APAGADOS", None),
           ("Aviónica", "APAGADA", lambda w: not s.avionics or not s.master),
           ("Selector de combustible", "AMBOS", lambda w: s.fuel_selector == 3)]
    L.append(("Antes de arrancar", pre))

    if fadec:
        start = [("Interruptor maestro", "ENCENDIDO", lambda w: s.master),
                 ("Luz anticolisión", "ENCENDIDA", lambda w: s.lights["beacon"]),
                 ("Potencia", "RALENTÍ", lambda w: all(en.throttle < 0.15 for en in _eng(w))),
                 ("MOTOR (ENGINE MASTER)" + (" IZQ y DER" if twin else ""), "ENCENDIDO",
                  lambda w: all(en.magnetos > 0 for en in _eng(w))),
                 ("ARRANQUE (precalentado ECU)", "ACCIONAR", lambda w: all(en.running for en in _eng(w))),
                 ("Carga del motor / presión de aceite", "EN VERDE", lambda w: all(en.oil_press > 25 for en in _eng(w))),
                 ("Aviónica", "ENCENDIDA", lambda w: s.avionics)]
    else:
        start = [("Mezcla", "RICA", lambda w: e.mixture > 0.9),
                 ("Gases", "ABIERTOS 1/4", lambda w: 0.08 < e.throttle < 0.4),
                 ("Interruptor maestro", "ENCENDIDO", lambda w: s.master),
                 ("Luz anticolisión", "ENCENDIDA", lambda w: s.lights["beacon"]),
                 ("Magnetos", "AMBOS", lambda w: e.magnetos == 3),
                 ("Arranque", "ACCIONAR", lambda w: e.running),
                 ("Presión de aceite", "EN VERDE (30 s)", lambda w: e.oil_press > 25),
                 ("Aviónica", "ENCENDIDA", lambda w: s.avionics)]
    L.append(("Arranque", start))

    runup = [("Freno de estacionamiento", "PUESTO", lambda w: s.parking_brake),
             ("Mandos de vuelo", "LIBRES Y CORRECTOS", None),
             ("Altímetro", "AJUSTADO AL QNH", lambda w: abs(w.kollsman - w.weather.qnh_hpa) < 1),
             ("Direccional", "ALINEADO CON LA BRÚJULA", lambda w: abs(((w.ind.dg - w.ind.compass) + 180) % 360 - 180) < 5),
             ("Radios y NAV", "AJUSTADOS", None),
             ("Compensador", "DESPEGUE", lambda w: -0.1 < ac.trim < 0.5),
             ("Flaps", "0° – 10°", lambda w: s.flaps <= 21)]
    if fadec:
        runup.append(("Prueba de ECU (botón ECU TEST)", "CORRECTA", None))
    else:
        runup += [("Motor", "1800 RPM", lambda w: e.rpm > 1700),
                  ("Magnetos", "COMPROBADOS (caída < 150 RPM)", None),
                  ("Mezcla", "RICA", lambda w: e.mixture > 0.9)]
    runup += [("Luces de aterrizaje y estroboscópicas", "ENCENDIDAS", lambda w: s.lights["landing"] and s.lights["strobe"]),
              ("Transpondedor", "ALT", None),
              ("Freno de estacionamiento", "QUITADO", lambda w: not s.parking_brake)]
    L.append(("Antes del despegue", runup))

    v = t.v
    to = [("Potencia", "MÁXIMA", lambda w: all(en.throttle > 0.95 for en in _eng(w))),
          ("Instrumentos de motor", "EN VERDE", None),
          (f"Rotación", f"{v['vr']} KIAS", None),
          (f"Ascenso", f"Vy {v['vy']} KIAS", None)]
    if t.retractable:
        to.append(("Tren (ascenso positivo)", "ARRIBA", lambda w: s.gear_pos < 0.05))
    to.append(("Flaps", "ARRIBA", lambda w: s.flaps < 1))
    L.append(("Despegue y ascenso", to))

    cr = [("Potencia", "DE CRUCERO", None),
          ("Compensador", "AJUSTADO", None),
          ("Instrumentos de motor", "EN VERDE", None)]
    if not fadec:
        cr.insert(1, ("Mezcla", "EMPOBRECIDA", lambda w: e.mixture < 0.97 or ac.alt_msl < 900))
    L.append(("Crucero", cr))

    app = [("ATIS / QNH", "OBTENIDO Y AJUSTADO", lambda w: abs(w.kollsman - w.weather.qnh_hpa) < 1),
           ("Selector de combustible", "AMBOS", lambda w: s.fuel_selector == 3),
           ("Luz de aterrizaje", "ENCENDIDA", lambda w: s.lights["landing"]),
           ("Piloto automático", "DESCONECTADO (antes de la toma)", lambda w: not w.ap.engaged)]
    if not fadec:
        app.insert(1, ("Mezcla", "RICA", lambda w: e.mixture > 0.9))
    if t.retractable:
        app.append(("Tren", "ABAJO — 3 VERDES", lambda w: s.gear_pos > 0.99))
    app += [("Flaps", "SEGÚN NECESIDAD", None),
            ("Velocidad en final", f"{v['vapp']} KIAS", None)]
    L.append(("Antes del aterrizaje", app))

    after = [("Flaps", "ARRIBA", lambda w: s.flaps < 1),
             ("Luces estroboscópicas", "APAGADAS", lambda w: not s.lights["strobe"]),
             ("Luz de rodaje", "ENCENDIDA", lambda w: s.lights["taxi"]),
             ("Transpondedor", "STBY", None)]
    L.append(("Después del aterrizaje", after))

    return L


def emergency_lists(world):
    """Listas de emergencia del POH/AFM (en el orden de la tableta)."""
    t = world.ac.t
    s = world.ac.sys
    e = s.engine
    fadec = t.fadec
    twin = s.twin
    v = t.v
    E = []
    if twin:
        E.append(("Falla de motor (bimotor)", [
            ("Control direccional", "MANTENER (pedal del motor bueno)", None),
            ("Potencia", "AMBAS A FONDO", lambda w: all(en.throttle > 0.95 for en in _eng(w)) or any(en.magnetos == 0 for en in _eng(w))),
            ("Identificar", "PIE MUERTO = MOTOR MUERTO", None),
            ("Verificar", "REDUCIR LA PALANCA SOSPECHOSA", None),
            ("Embanderar", "MOTOR del motor parado: OFF", lambda w: any(en.magnetos == 0 for en in _eng(w))),
            ("Velocidad", f"Vyse {v.get('vyse', 82)} KIAS (línea azul)", None),
            ("Alabeo", "2° – 5° HACIA EL MOTOR BUENO", None),
            ("Tren y flaps", "ARRIBA", lambda w: s.gear_pos < 0.05 and s.flaps < 1)]))
    else:
        eng = [("Velocidad", f"MEJOR PLANEO {v['vglide']} KIAS", None),
               ("Lugar de aterrizaje", "ELEGIR", None),
               ("Selector de combustible", "AMBOS", lambda w: s.fuel_selector == 3)]
        if not fadec:
            eng += [("Mezcla", "RICA", lambda w: e.mixture > 0.9),
                    ("Magnetos", "AMBOS (o ARRANQUE si la hélice está parada)", lambda w: e.magnetos == 3)]
        else:
            eng += [("MOTOR (ENGINE MASTER)", "OFF y ON (reinicio de ECU)", None)]
        eng += [("Si no arranca: radio", "MAYDAY 121.5 / transpondedor 7700", lambda w: w.xpdr == 7700),
                ("Antes de tocar: maestro", "APAGADO (con flaps ya puestos)", None)]
        E.append(("Falla de motor en vuelo", eng))
    fire = []
    if fadec:
        fire.append(("MOTOR (ENGINE MASTER)", "OFF", lambda w: e.magnetos == 0))
    else:
        fire.append(("Mezcla", "CORTE (IDLE CUT-OFF)", lambda w: e.mixture < 0.1))
    fire += [("Selector de combustible", "CERRADO", lambda w: s.fuel_selector == 0),
             ("Bomba eléctrica de combustible", "OFF", lambda w: not s.fuel_pump),
             ("Interruptor maestro", "OFF", lambda w: not s.master),
             ("Calefacción y aire de cabina", "CERRADOS", None),
             ("Velocidad", f"{int(v['vy'] * 1.3)} KIAS (picar para apagar las llamas)", None),
             ("Aterrizaje forzoso", "EJECUTAR", None)]
    E.append(("Fuego de motor en vuelo", fire))
    E.append(("Humo / fuego eléctrico", [
        ("Interruptor maestro", "OFF", lambda w: not s.master),
        ("Aviónica", "OFF", lambda w: not s.avionics),
        ("Extintor", "DESCARGAR", lambda w: s.extinguisher <= 0),
        ("Ventilación", "ABRIR cuando el fuego esté apagado", None),
        ("Aterrizar", "LO ANTES POSIBLE", None)]))
    E.append(("Falla eléctrica / alternador", [
        ("Amperímetro / voltímetro", "COMPROBAR", None),
        ("Alternador (ALT)", "OFF y luego ON (reinicio)", None),
        ("Cargas no esenciales", "APAGAR (luces, pitot, bomba)", lambda w: not s.pitot_heat and not s.lights["landing"]),
        ("Aterrizar", "EN EL AERÓDROMO MÁS CERCANO", None)]))
    E.append(("Falla de radio (comunicaciones)", [
        ("Volumen, frecuencia y auriculares", "COMPROBAR", None),
        ("Transpondedor", "7600", lambda w: w.xpdr == 7600),
        ("Circuito", "INCORPORARSE Y OBSERVAR LA TORRE", None),
        ("Luz VERDE fija", "AUTORIZADO A ATERRIZAR", None),
        ("Luz ROJA fija", "CEDA EL PASO, SIGA EN CIRCUITO", None),
        ("Alabear las alas", "PARA ACUSAR RECIBO", None)]))
    if t.retractable:
        E.append(("El tren no baja", [
            ("Interruptor maestro y cortacircuito", "COMPROBAR", lambda w: s.master),
            ("Palanca del tren", "ABAJO", lambda w: s.gear_down),
            ("Velocidad", "POR DEBAJO DE 100 KIAS", lambda w: w.ind.ias < 100),
            ("Extensión de emergencia", "ACCIONAR (Mayús+G)", lambda w: s.gear_emergency),
            ("Tres luces verdes", "COMPROBAR", lambda w: s.gear_pos > 0.99)]))
    E.append(("Compensador desbocado", [
        ("Volante", "SUJETAR FIRME", None),
        ("Desconexión PA / compensador", "PULSAR (Z)", lambda w: not s.trim_cb),
        ("Cortacircuito del compensador", "FUERA", lambda w: not s.trim_cb),
        ("Compensar", "A MANO", None)]))
    E.append(("Puerta abierta en vuelo", [
        ("Volar el avión", "NO DISTRAERSE", None),
        ("Velocidad", "POR DEBAJO DE 80 KIAS", lambda w: w.ind.ias < 80),
        ("Ventanilla", "ABRIR (iguala presiones)", None),
        ("Puerta", "CERRAR", lambda w: not s.failures.get("door")),
        ("Si no cierra", "ATERRIZAR Y CERRAR EN TIERRA", None)]))
    if not fadec:
        E.append(("Motor irregular (magnetos)", [
            ("Mezcla", "AJUSTAR", None),
            ("Magnetos", "PROBAR DER e IZQ", None),
            ("Magneto que funciona", "SELECCIONAR (IZQ)", lambda w: e.magnetos == 2),
            ("Aterrizar", "EN EL AERÓDROMO MÁS CERCANO", None)]))
    E.append(("Fuga de combustible", [
        ("Indicadores de combustible", "VIGILAR", None),
        ("Selector", "AMBOS", lambda w: s.fuel_selector == 3),
        ("Aterrizar", "LO ANTES POSIBLE", None)]))
    E.append(("Entrada inadvertida en nubes", [
        ("Instrumentos", "CONFIAR EN ELLOS", None),
        ("Alas", "NIVELADAS", lambda w: abs(w.ac.roll) < 0.1),
        ("Viraje de 180°", "RÉGIMEN ESTÁNDAR, ≤ 20° DE ALABEO", None),
        ("Altitud", "MANTENER", None),
        ("Salir de las nubes", "Y VOLVER A VFR", None)]))
    return E


FAIL_TO_LIST = {"fire": "Fuego de motor en vuelo", "smoke": "Humo / fuego eléctrico",
                "electrical": "Falla eléctrica / alternador", "alternator": "Falla eléctrica / alternador",
                "radio": "Falla de radio (comunicaciones)", "gear": "El tren no baja", "trim": "Compensador desbocado",
                "door": "Puerta abierta en vuelo", "magneto": "Motor irregular (magnetos)", "fuel_leak": "Fuga de combustible",
                "engine": "Falla de motor en vuelo", "engine2": "Falla de motor (bimotor)"}


def suggested_emergency(world, elists):
    """Nombre de la lista de emergencia que corresponde a la falla activa (o None)."""
    names = [n for n, _ in elists]
    order = ["fire", "smoke", "engine", "engine2", "electrical", "alternator", "gear", "trim", "door", "radio",
             "magneto", "fuel_leak"]
    fl = world.ac.sys.failures
    for k in order:
        v = fl.get(k)
        if v and k in FAIL_TO_LIST:
            n = FAIL_TO_LIST[k]
            if world.ac.sys.twin and k in ("engine", "engine2"):
                n = "Falla de motor (bimotor)"
            if n in names:
                return n
    return None


def suggested_phase(world, lists):
    """Índice de la lista que corresponde a la situación actual."""
    ac = world.ac
    s = ac.sys
    names = [n for n, _ in lists]

    def idx(name):
        return names.index(name) if name in names else 0
    if ac.on_ground and not any(en.running for en in s.engines):
        return idx("Antes de arrancar") if not s.master else idx("Arranque")
    if ac.on_ground:
        return idx("Antes del despegue") if ac.gs < 3 else idx("Despegue y ascenso")
    if ac.agl / FT < 1000 and ac.vs_fpm > 200:
        return idx("Despegue y ascenso")
    near = min(((ac.pos[0] - a.ref[0]) ** 2 + (ac.pos[1] - a.ref[1]) ** 2) ** 0.5 for a in world.airports) < 9000
    if near and (ac.vs_fpm < -150 or ac.agl / FT < 1500):
        return idx("Antes del aterrizaje")
    return idx("Crucero")
