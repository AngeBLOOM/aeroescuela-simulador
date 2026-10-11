"""Datos aerodinámicos, másicos y de motor de las aeronaves de entrenamiento.

Valores basados en datos públicos de la Cessna 172 (Roskam, manuales POH)
y ajustados para que las velocidades características coincidan con el POH.
"""
import math


class Gear:
    def __init__(self, name, pos, k, c, steer=False, brake=False, retract=False):
        self.name = name
        self.pos = pos            # posición en ejes cuerpo (m) del punto de contacto
        self.k = k                # rigidez (N/m)
        self.c = c                # amortiguamiento (N·s/m)
        self.steer = steer
        self.brake = brake
        self.retract = retract


class AircraftType:
    pass


def _cessna172_base():
    """Base común: el C172 tal como se ajustó al principio. Los demás aviones parten de ella y cambian lo suyo;
    el C172S de referencia (cessna172) le añade además el ajuste a su manual."""
    a = AircraftType()
    a.id = "c172"
    a.name = "Cessna 172S Skyhawk"
    a.short = "C172S"
    a.empty_mass = 760.0          # kg (incluye piloto e instructor)
    a.payload = 170.0
    a.fuel_capacity = 200.0       # litros utilizables
    a.fuel_density = 0.72
    a.inertia = (1285.0, 1825.0, 2667.0)   # Ixx, Iyy, Izz (kg m2) a ~1040 kg
    a.ref_mass = 1043.0

    # geometría
    a.S = 16.2
    a.b = 11.0
    a.c = 1.49
    a.AR = a.b ** 2 / a.S

    # sustentación
    a.CL0 = 0.25
    a.CLa = 4.8
    a.CLq = 3.9
    a.CLde = 0.43
    a.alpha_stall = math.radians(16.5)
    a.alpha_stall_flap_delta = math.radians(-1.5)   # con flaps completos
    a.CL_flaps = 0.45                                # incremento a 30°
    # resistencia
    a.CD0 = 0.030
    a.e = 0.75
    a.CD_flaps = 0.055
    a.CD_beta = 0.25
    a.CD_gear = 0.0               # tren fijo incluido en CD0
    # fuerza lateral
    a.CYb = -0.31
    a.CYdr = 0.187
    a.CYp = -0.037
    a.CYr = 0.21
    # alabeo
    a.Clb = -0.089
    a.Clp = -0.47
    a.Clr = 0.096
    a.Clda = 0.178
    a.Cldr = 0.0147
    # cabeceo
    a.Cm0 = 0.02
    a.Cma = -0.89
    a.Cmq = -12.4
    a.Cmadot = -5.2
    a.Cmde = -1.10
    a.Cm_flaps = 0.035
    a.Cm_stall = -0.25
    # guiñada
    a.Cnb = 0.065
    a.Cnp = -0.03
    a.Cnr = -0.099
    a.Cnda = -0.025
    a.Cndr = 0.0657

    # mandos (rad)
    a.elev_up = math.radians(26)
    a.elev_down = math.radians(21)
    a.ail_max = math.radians(18)
    a.rud_max = math.radians(17)
    a.trim_range = math.radians(9)
    a.flap_settings = [0, 10, 20, 30]
    a.flap_rate = 4.5             # grados/s
    a.nose_steer_max = math.radians(10)
    a.nose_steer_rudder = math.radians(30)   # con freno diferencial/pedal a fondo

    # motor y hélice (Lycoming IO-360-L2A 180 hp, hélice de paso fijo)
    a.engine_power = 134000.0     # W
    a.rpm_max = 2700.0
    a.rpm_redline = 2700.0
    a.rpm_idle = 650.0
    a.prop_eff = 0.80
    a.prop_vc = 42.0              # m/s (fija empuje estático)
    a.prop_radius = 0.95
    a.fixed_pitch = True
    a.retractable = False
    a.p_factor = 0.045            # brazo de momento de guiñada (m)
    a.torque_roll = 0.30
    # reglaje de fábrica: aleta fija del timón y alerón compensan el par en crucero
    a.rig_yaw = 2.2e-4
    a.rig_roll = 3.3e-4

    # velocidades características (KIAS)
    a.v = dict(vs0=40, vs1=48, vr=55, vx=62, vy=74, vfe=85, va=105, vno=129,
               vne=163, vapp=65, vglide=68, vcruise=110, vref=61)
    a.flap_vfe = {10: 110, 20: 85, 30: 85}
    a.g_limit = (3.8, -1.52)

    # tren de aterrizaje (posición del punto de contacto en ejes cuerpo)
    a.gears = [
        Gear("nariz", (1.55, 0.0, 1.17), 45000.0, 3200.0, steer=True),
        Gear("izq", (-0.38, -1.25, 1.17), 70000.0, 5500.0, brake=True),
        Gear("der", (-0.38, 1.25, 1.17), 70000.0, 5500.0, brake=True),
    ]
    # puntos de choque (fuselaje/hélice/puntas)
    a.contacts = [
        ("hélice", (1.95, 0.0, 0.96)),
        ("cola", (-4.6, 0.0, 0.22)),
        ("punta izq", (0.0, -5.5, -0.85)),
        ("punta der", (0.0, 5.5, -0.85)),
        ("fuselaje", (0.6, 0.0, 0.55)),
        ("techo", (0.3, 0.0, -1.3)),
    ]
    a.eye = (0.55, -0.32, -0.62)
    a.low_wing = False
    # rasgos generales (los redefinen otros aviones)
    a.engines_y = [0.0]            # posición lateral de cada motor (m)
    a.fadec = False                # motor diésel con control electrónico (sin mezcla ni paso)
    a.carburetor = False           # motor de carburador (hielo en el carburador y calefacción); el 172S es de inyección
    a.can_feather = False
    a.t_tail = False
    a.canopy = False               # cúpula de burbuja en lugar de techo y puertas
    a.slipstream = 0.17            # cuánto sopla la hélice sobre la cola
    a.default_cockpit = "analog"
    a.paint = ((0.93, 0.93, 0.91), (0.10, 0.22, 0.55))
    a.category = "Monomotor de ala alta · entrenamiento básico"
    return a


def cessna172():
    """Cessna 172S, el avión de referencia: la base con el ajuste a su manual (POH). Las cifras que se comprueban,
    con su tolerancia, están en sim/poh.py y las mide tools/validacion.py (prueba test_validacion)."""
    a = _cessna172_base()
    a.CD0 = 0.026                 # crucero de 124 KTAS al 75 % a 8000 ft
    a.e = 0.90                    # con CD0: ascenso cerca de 730 ft/min a Vy
    a.prop_vc = 44.0              # empuje estático: carrera de despegue de pista corta de 960 ft
    a.alpha_stall_flap_delta = math.radians(-0.3)   # pérdida con flaps 30° a 48 KCAS
    a.prop_windmill = 0.57        # hélice en molinete: planeo de 9:1 (1,5 NM por cada 1000 ft)
    a.brake_max = 0.35            # par de los frenos: carrera de aterrizaje de 575 ft con frenada máxima
    # con menos resistencia el crucero pide menos potencia (menos par): reglaje neutro con mandos sueltos a ~108 kt
    a.rig_roll = 2.8e-4
    a.rig_yaw = 1.75e-4
    return a


def piper_arrow():
    a = _cessna172_base()
    a.id = "pa28r"
    a.name = "Piper PA-28R-201 Arrow"
    a.short = "PA-28R"
    a.empty_mass = 800.0
    a.fuel_capacity = 182.0
    a.inertia = (1150.0, 1950.0, 2850.0)
    a.ref_mass = 1110.0
    a.S = 15.8
    a.b = 10.8
    a.c = 1.6
    a.AR = a.b ** 2 / a.S
    a.CD0 = 0.0245
    a.CD_gear = 0.012
    a.Cl_dihedral_scale = 1.0
    a.Clb = -0.07
    a.CL_flaps = 0.50
    a.alpha_stall = math.radians(17.0)
    a.engine_power = 149000.0     # 200 hp
    a.prop_vc = 48.0
    a.prop_eff = 0.84
    a.fixed_pitch = False
    a.retractable = True
    a.flap_settings = [0, 10, 25, 40]
    a.flap_vfe = {10: 103, 25: 103, 40: 103}
    a.v = dict(vs0=55, vs1=60, vr=65, vx=78, vy=90, vfe=103, va=118, vno=150,
               vne=183, vapp=75, vglide=79, vcruise=137, vref=72, vlo=129)
    a.gears = [
        Gear("nariz", (1.5, 0.0, 1.12), 45000.0, 3300.0, steer=True, retract=True),
        Gear("izq", (-0.35, -1.6, 1.12), 72000.0, 5700.0, brake=True, retract=True),
        Gear("der", (-0.35, 1.6, 1.12), 72000.0, 5700.0, brake=True, retract=True),
    ]
    a.contacts = [
        ("hélice", (1.95, 0.0, 0.92)),
        ("cola", (-4.6, 0.0, 0.25)),
        ("punta izq", (0.0, -5.4, -0.15)),
        ("punta der", (0.0, 5.4, -0.15)),
        ("vientre", (0.4, 0.0, 0.62)),
        ("vientre trasero", (-1.5, 0.0, 0.55)),
        ("techo", (0.3, 0.0, -1.25)),
    ]
    a.low_wing = True
    a.eye = (0.45, -0.32, -0.55)
    a.paint = ((0.93, 0.93, 0.91), (0.65, 0.08, 0.08))
    a.category = "Monomotor complejo · tren retráctil y hélice de paso variable"
    return a


def diamond_da40():
    """Diamond DA40 NG: monomotor diésel (FADEC), ala baja, cola en T, G1000."""
    a = _cessna172_base()
    a.id = "da40"
    a.name = "Diamond DA40 NG"
    a.short = "DA40 NG"
    a.category = "Monomotor moderno · diésel FADEC, cola en T, G1000"
    a.empty_mass = 960.0
    a.payload = 160.0
    a.fuel_capacity = 148.0
    a.fuel_density = 0.81
    a.inertia = (1350.0, 1750.0, 2900.0)
    a.ref_mass = 1250.0
    a.S = 13.54
    a.b = 11.94
    a.c = 1.17
    a.AR = a.b ** 2 / a.S
    a.CL0 = 0.30
    a.CLa = 5.2
    a.alpha_stall = __import__("math").radians(15.5)
    a.CL_flaps = 0.55
    a.CD0 = 0.0235
    a.e = 0.82
    a.CD_flaps = 0.07
    a.Clb = -0.10
    a.Cma = -1.0
    a.Cmde = -1.15
    a.Cm0 = 0.035
    a.flap_settings = [0, 20, 42]
    a.flap_vfe = {20: 108, 42: 91}
    a.flap_rate = 7.0
    a.engine_power = 125000.0      # Austro AE300, 168 hp
    a.prop_vc = 44.0
    a.prop_eff = 0.82
    a.fixed_pitch = False
    a.fadec = True
    a.prop_radius = 0.90
    a.slipstream = 0.12
    a.t_tail = True
    a.canopy = True
    a.low_wing = True
    a.default_cockpit = "glass"
    a.rig_yaw = 1.8e-4
    a.rig_roll = 2.6e-4
    a.v = dict(vs0=49, vs1=55, vr=59, vx=68, vy=72, vfe=91, va=108, vno=129,
               vne=178, vapp=72, vglide=76, vcruise=130, vref=65)
    a.gears = [
        Gear("nariz", (1.45, 0.0, 1.06), 46000.0, 3400.0, steer=True),
        Gear("izq", (-0.25, -1.5, 1.06), 82000.0, 6200.0, brake=True),
        Gear("der", (-0.25, 1.5, 1.06), 82000.0, 6200.0, brake=True),
    ]
    a.contacts = [
        ("hélice", (2.15, 0.0, 0.92)),
        ("cola", (-5.2, 0.0, 0.30)),
        ("punta izq", (0.0, -5.97, -0.20)),
        ("punta der", (0.0, 5.97, -0.20)),
        ("vientre", (0.4, 0.0, 0.60)),
        ("cúpula", (0.3, 0.0, -1.15)),
    ]
    a.eye = (0.40, -0.30, -0.64)
    a.paint = ((0.95, 0.95, 0.95), (0.12, 0.28, 0.55))
    return a


def diamond_da42():
    """Diamond DA42 NG: bimotor diésel, tren retráctil, cola en T, G1000."""
    a = diamond_da40()
    a.id = "da42"
    a.name = "Diamond DA42 NG Twin Star"
    a.short = "DA42 NG"
    a.category = "Bimotor · habilitación multimotor (Vmc, falla de motor)"
    a.empty_mass = 1470.0
    a.payload = 170.0
    a.fuel_capacity = 190.0
    a.inertia = (3600.0, 3300.0, 6400.0)
    a.ref_mass = 1800.0
    a.S = 16.29
    a.b = 13.55
    a.c = 1.22
    a.AR = a.b ** 2 / a.S
    a.CL0 = 0.28
    a.CLa = 5.3
    a.alpha_stall = __import__("math").radians(15.0)
    a.CL_flaps = 0.55
    a.CD0 = 0.0265
    a.CD_gear = 0.016
    a.Cnb = 0.075
    a.Cndr = 0.037
    a.rud_max = __import__("math").radians(25)
    a.Cnr = -0.12
    a.engines_y = [-1.68, 1.68]
    a.engine_power = 125000.0      # por motor
    a.can_feather = True
    a.retractable = True
    a.slipstream = 0.03
    a.p_factor = 0.02
    a.torque_roll = 0.15
    a.rig_yaw = 1.0e-4
    a.rig_roll = 2.4e-4
    a.flap_settings = [0, 20, 42]
    a.flap_vfe = {20: 137, 42: 111}
    a.v = dict(vs0=58, vs1=63, vr=72, vx=79, vy=85, vfe=111, va=119, vno=155,
               vne=194, vapp=85, vglide=82, vcruise=160, vref=78, vlo=156,
               vmc=68, vyse=82, vxse=79)
    a.gears = [
        Gear("nariz", (1.75, 0.0, 1.05), 50000.0, 3800.0, steer=True, retract=True),
        Gear("izq", (-0.30, -1.68, 1.05), 105000.0, 8000.0, brake=True, retract=True),
        Gear("der", (-0.30, 1.68, 1.05), 105000.0, 8000.0, brake=True, retract=True),
    ]
    a.contacts = [
        ("hélice izq", (1.35, -1.68, 0.90)),
        ("hélice der", (1.35, 1.68, 0.90)),
        ("cola", (-5.5, 0.0, 0.30)),
        ("punta izq", (0.0, -6.77, -0.25)),
        ("punta der", (0.0, 6.77, -0.25)),
        ("vientre", (0.6, 0.0, 0.58)),
        ("vientre trasero", (-1.4, 0.0, 0.50)),
        ("cúpula", (0.2, 0.0, -1.12)),
    ]
    a.eye = (0.55, -0.30, -0.62)
    a.paint = ((0.95, 0.95, 0.95), (0.55, 0.58, 0.62))
    return a


def cessna152():
    """Cessna 152: biplaza de ala alta, 110 hp, el entrenador básico más extendido."""
    a = _cessna172_base()
    a.id = "c152"
    a.name = "Cessna 152"
    a.short = "C152"
    a.carburetor = True            # Lycoming O-235 de carburador
    a.empty_mass = 560.0
    a.payload = 150.0
    a.fuel_capacity = 92.0
    a.inertia = (900.0, 1250.0, 1900.0)
    a.ref_mass = 740.0
    a.S = 14.9
    a.b = 10.2
    a.c = 1.47
    a.AR = a.b ** 2 / a.S
    a.CD0 = 0.032
    a.CL_flaps = 0.42
    a.engine_power = 82000.0      # Lycoming O-235 de 110 hp
    a.rpm_max = 2550.0
    a.rpm_redline = 2550.0
    a.prop_vc = 36.0
    a.prop_radius = 0.88
    a.v = dict(vs0=35, vs1=40, vr=50, vx=55, vy=67, vfe=85, va=104, vno=111,
               vne=149, vapp=60, vglide=60, vcruise=95, vref=54)
    a.flap_vfe = {10: 85, 20: 85, 30: 85}
    a.gears = [
        Gear("nariz", (1.35, 0.0, 1.05), 32000.0, 2400.0, steer=True),
        Gear("izq", (-0.35, -1.0, 1.05), 50000.0, 4000.0, brake=True),
        Gear("der", (-0.35, 1.0, 1.05), 50000.0, 4000.0, brake=True),
    ]
    a.contacts = [
        ("hélice", (1.75, 0.0, 0.88)),
        ("cola", (-4.2, 0.0, 0.2)),
        ("punta izq", (0.0, -5.1, -0.8)),
        ("punta der", (0.0, 5.1, -0.8)),
        ("fuselaje", (0.5, 0.0, 0.5)),
        ("techo", (0.3, 0.0, -1.2)),
    ]
    a.eye = (0.5, -0.28, -0.58)
    a.paint = ((0.95, 0.95, 0.93), (0.70, 0.12, 0.10))
    a.category = "Biplaza de ala alta · primer entrenador"
    return a


def piper_warrior():
    """Piper PA-28-161 Warrior III: ala baja, tren fijo y hélice de paso fijo, 160 hp."""
    a = piper_arrow()
    a.id = "pa28w"
    a.name = "Piper PA-28-161 Warrior III"
    a.short = "PA-28-161"
    a.carburetor = True            # Lycoming O-320 de carburador
    a.empty_mass = 690.0
    a.payload = 200.0
    a.fuel_capacity = 182.0
    a.ref_mass = 1000.0
    a.CD0 = 0.031
    a.CD_gear = 0.0
    a.engine_power = 119000.0     # Lycoming O-320 de 160 hp
    a.rpm_max = 2700.0
    a.prop_vc = 42.0
    a.prop_eff = 0.80
    a.fixed_pitch = True
    a.retractable = False
    a.flap_settings = [0, 10, 25, 40]
    a.flap_vfe = {10: 103, 25: 103, 40: 103}
    a.v = dict(vs0=44, vs1=50, vr=55, vx=63, vy=79, vfe=103, va=111, vno=126,
               vne=160, vapp=66, vglide=73, vcruise=115, vref=63)
    a.gears = [
        Gear("nariz", (1.5, 0.0, 1.1), 45000.0, 3300.0, steer=True),
        Gear("izq", (-0.35, -1.6, 1.1), 72000.0, 5700.0, brake=True),
        Gear("der", (-0.35, 1.6, 1.1), 72000.0, 5700.0, brake=True),
    ]
    a.paint = ((0.94, 0.94, 0.92), (0.10, 0.20, 0.45))
    a.category = "Monomotor de ala baja · tren fijo, entrenamiento básico"
    return a


def cirrus_sr20():
    """Cirrus SR20 G6: ala baja de material compuesto, hélice de velocidad constante, Perspective (G1000)."""
    a = piper_arrow()
    a.id = "sr20"
    a.name = "Cirrus SR20"
    a.short = "SR20"
    a.empty_mass = 1000.0
    a.payload = 190.0
    a.fuel_capacity = 212.0
    a.inertia = (1500.0, 2300.0, 3400.0)
    a.ref_mass = 1300.0
    a.S = 13.5
    a.b = 11.68
    a.c = 1.2
    a.AR = a.b ** 2 / a.S
    a.CD0 = 0.026
    a.CD_gear = 0.0
    a.CL_flaps = 0.55
    a.alpha_stall = math.radians(16.0)
    a.engine_power = 160000.0     # Continental IO-360-ES de 215 hp
    a.prop_vc = 50.0
    a.prop_eff = 0.84
    a.fixed_pitch = False
    a.retractable = False
    a.flap_settings = [0, 16, 32]
    a.flap_vfe = {16: 119, 32: 104}
    a.v = dict(vs0=56, vs1=65, vr=65, vx=81, vy=96, vfe=104, va=131, vno=163,
               vne=200, vapp=78, vglide=92, vcruise=150, vref=78)
    a.gears = [
        Gear("nariz", (1.45, 0.0, 1.1), 48000.0, 3500.0, steer=False),
        Gear("izq", (-0.4, -1.6, 1.1), 80000.0, 6000.0, brake=True),
        Gear("der", (-0.4, 1.6, 1.1), 80000.0, 6000.0, brake=True),
    ]
    a.nose_steer_max = math.radians(0)          # rueda de morro libre: se dirige con frenos diferenciales
    a.nose_steer_rudder = math.radians(20)
    a.default_cockpit = "glass"
    a.paint = ((0.96, 0.96, 0.96), (0.15, 0.15, 0.17))
    a.category = "Monomotor moderno · compuesto, Perspective/G1000, paracaídas CAPS"
    return a


AIRCRAFT = {"c152": cessna152, "c172": cessna172, "pa28w": piper_warrior, "pa28r": piper_arrow,
            "sr20": cirrus_sr20, "da40": diamond_da40, "da42": diamond_da42}
