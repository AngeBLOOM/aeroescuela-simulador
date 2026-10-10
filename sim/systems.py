"""Sistemas del avión: motor y hélice, combustible, eléctrico, vacío, flaps, tren y luces."""
import math

from .mathx import approach, clamp

INHG_PER_PA = 1.0 / 3386.39


class Engine:
    def __init__(self, t):
        self.t = t
        self.throttle = 0.0
        self.mixture = 1.0
        self.prop_lever = 1.0
        self.magnetos = 3            # 0 OFF, 1 DER, 2 IZQ, 3 AMBOS
        self.starter = False
        self.running = False
        self.failed = False
        self.rpm = 0.0
        self.pf = 0.0                # fracción de potencia efectiva (con retardo)
        self.crank_time = 0.0
        self.oil_temp = 60.0         # °F
        self.oil_press = 0.0         # psi
        self.cht = 60.0
        self.egt = 60.0
        self.map_inhg = 29.92
        self.fuel_flow = 0.0         # L/h
        self.thrust = 0.0
        self.torque = 0.0
        self.rough = 0.0             # 0..1 funcionamiento irregular
        self.shaft_power = 0.0
        self.feathered = False
        self.load = 0.0              # % de carga (motores FADEC)
        self.bad_mag = 0             # magneto averiado: 1 derecho, 2 izquierdo
        self.carb_ice = 0.0          # hielo en el carburador 0..1 (solo motores de carburador)
        self.carb_heat = False       # calefacción al carburador (aire caliente sin filtrar)
        self.oat_c = 15.0            # temperatura exterior y humedad (las pone Systems antes de cada paso)
        self.dew_spread = 8.0
        self.force_ice = False       # el instructor provoca la formación de hielo

    def set_running(self, run=True):
        self.running = run and not self.failed
        if self.running:
            self.rpm = max(self.rpm, self.t.rpm_idle + 100)
            self.oil_temp = max(self.oil_temp, 170.0)
            self.cht = max(self.cht, 300.0)
            self.oil_press = 70.0
            self.pf = 0.05

    def best_mixture(self, sigma):
        return clamp(sigma ** 1.6, 0.35, 1.0)

    def update(self, dt, rho, p_amb, V, fuel_ok, battery_ok):
        t = self.t
        sigma = rho / 1.225
        m_best = self.best_mixture(sigma)
        if t.fadec:
            # el FADEC ajusta la mezcla y el paso: el piloto solo mueve la potencia
            self.mixture = m_best if self.magnetos > 0 else self.mixture
        dm = self.mixture - m_best
        if dm >= 0:
            mix_f = 1.0 - 1.4 * dm * dm
        else:
            mix_f = 1.0 - 5.0 * dm * dm
        self.rough = clamp((-dm - 0.18) / 0.2, 0.0, 1.0) if dm < 0 else 0.0
        mag_f = {0: 0.0, 1: 0.9, 2: 0.88, 3: 1.0}[self.magnetos]
        bad = getattr(self, "bad_mag", 0)
        if bad and self.magnetos in (bad, 3):
            # magneto averiado: en AMBOS el motor va irregular; solo con el malo, casi se para
            if self.magnetos == 3:
                mag_f = 0.9
                self.rough = max(self.rough, 0.35)
            else:
                mag_f = 0.15
                self.rough = 1.0
        dens_f = max(0.0, sigma - (1 - sigma) / 7.55)

        # hielo en el carburador: al expandirse en el venturi el aire se enfría hasta 20-30 °C; con aire húmedo y
        # -15..32 °C fuera se forma hielo, más con el gas reducido. La calefacción lo funde (el agua hace que el motor
        # vaya peor unos segundos) a cambio de algo de potencia.
        thr = clamp(self.throttle, 0.0, 1.0)
        ice_f = 1.0
        if t.carburetor:
            if self.carb_heat:
                if self.running or V > 25:
                    if self.carb_ice > 0.15 and self.running:
                        self.rough = max(self.rough, 0.8 * self.carb_ice)
                    self.carb_ice = max(0.0, self.carb_ice - dt / (35.0 if self.running else 70.0))
                ice_f = 0.9
            elif self.running:
                humid = clamp((10.0 - self.dew_spread) / 8.0, 0.0, 1.0)      # rocío a 2 °C o menos: máximo
                temp = clamp((self.oat_c + 15.0) / 7.0, 0.0, 1.0) * clamp((32.0 - self.oat_c) / 7.0, 0.0, 1.0)
                risk = 1.0 if self.force_ice else humid * temp
                self.carb_ice = min(1.0, self.carb_ice + risk * (1.0 - 0.6 * thr) * dt / 240.0)
            ice_f *= 1.0 - 0.75 * self.carb_ice
            if self.carb_ice > 0.5:
                self.rough = max(self.rough, (self.carb_ice - 0.5) * 1.6)

        ignition = (self.magnetos > 0 and fuel_ok and self.mixture > 0.08 and not self.failed
                    and self.carb_ice < 0.95)
        if self.running and (not ignition or dm < -0.42):
            self.running = False

        # presión de admisión
        p_inhg = p_amb * INHG_PER_PA
        if self.running:
            self.map_inhg = p_inhg * (0.28 + 0.69 * thr) - (0.0 if thr > 0.2 else 0.0)
        else:
            self.map_inhg = approach(self.map_inhg, p_inhg, dt * 10.0)

        if self.running:
            thr_eff = 0.025 + 0.975 * thr
            pf_cmd = thr_eff * dens_f * mix_f * mag_f * ice_f
            if self.rough > 0:
                pf_cmd *= 1.0 - 0.35 * self.rough * (0.5 + 0.5 * math.sin(self.crank_time * 37.0))
        else:
            pf_cmd = 0.0
        self.pf += (pf_cmd - self.pf) * min(1.0, dt / 0.5)
        self.crank_time += dt

        # rpm de equilibrio
        if self.running and t.fadec:
            rpm_eq = 890.0 + 1410.0 * min(1.0, max(self.pf, 0.0) / 0.92) ** 0.55
        elif self.running:
            rpm_eq = 2330.0 * max(self.pf, 0.0) ** (1 / 3) + 7.0 * max(V, 0)
            if not t.fixed_pitch:
                # hélice de velocidad constante: el regulador mantiene las rpm elegidas
                rpm_set = 2100.0 + 600.0 * self.prop_lever
                rpm_eq = min(rpm_eq + 450.0, rpm_set)
        else:
            rpm_eq = max(0.0, 25.0 * V - 120.0) if V > 15 else 0.0
            if self.starter and battery_ok:
                rpm_eq = max(rpm_eq, 260.0)
        tau = 0.7 if rpm_eq > self.rpm else 1.2
        self.rpm += (rpm_eq - self.rpm) * min(1.0, dt / tau)
        if self.rpm < 5:
            self.rpm = 0.0

        # arranque
        if not self.running and ignition and not self.failed:
            if self.starter and battery_ok and self.rpm > 180:
                self.crank_time_start = getattr(self, "crank_time_start", 0.0) + dt
                if self.crank_time_start > 1.2 and self.mixture > 0.4:
                    self.running = True
                    self.crank_time_start = 0.0
            elif self.rpm > 350:            # rearranque por molinete
                self.running = True
        if not self.starter:
            self.crank_time_start = 0.0

        # empuje
        self.shaft_power = t.engine_power * max(self.pf, 0.0)
        eff = t.prop_eff
        if not t.fixed_pitch:
            eff *= 1.0 + 0.05 * clamp(V / 70.0, 0, 1)
        self.feathered = t.can_feather and not self.running and self.magnetos == 0
        if self.running:
            self.thrust = eff * self.shaft_power / math.sqrt(V * V + t.prop_vc ** 2)
        elif self.feathered:
            self.thrust = -0.5 * rho * V * V * 0.012
            self.rpm *= 0.97
        else:
            self.thrust = -0.5 * rho * V * V * 0.15 * (1.0 if self.rpm > 50 else 0.6)
        self.load = 100.0 * max(self.pf, 0.0) / 0.92 if self.running else 0.0
        omega = max(self.rpm, 300.0) * 2 * math.pi / 60
        self.torque = self.shaft_power / omega if self.running else 0.0

        # consumo y temperaturas (°F, psi)
        if self.running:
            self.fuel_flow = (3.0 + 44.0 * self.pf * t.engine_power / 134000.0) * (0.75 + 0.25 * self.mixture / m_best)
        else:
            self.fuel_flow = 0.0
        oil_target = (110.0 + 115.0 * self.pf) if self.running else 60.0
        self.oil_temp += (oil_target - self.oil_temp) * min(1.0, dt / 60.0)
        cht_target = (230.0 + 260.0 * self.pf + 60 * max(0, -dm)) if self.running else 60.0
        self.cht += (cht_target - self.cht) * min(1.0, dt / 40.0)
        peak = 1.0 - clamp(abs(dm + 0.06) / 0.3, 0.0, 1.0)
        egt_target = (900.0 + 450.0 * self.pf + 180.0 * peak) if self.running else 60.0
        self.egt += (egt_target - self.egt) * min(1.0, dt / 4.0)
        op_target = (min(88.0, 22.0 + self.rpm / 2700.0 * 68.0) * clamp((260 - self.oil_temp) / 100 + 0.4, 0.7, 1.15)
                     if self.running else 0.0)
        self.oil_press += (op_target - self.oil_press) * min(1.0, dt / 1.5)
        return self.fuel_flow * dt / 3600.0


class Systems:
    """Agrupa sistemas eléctricos, de vacío, combustible, flaps, tren y luces."""

    def __init__(self, t):
        self.t = t
        self.engines = [Engine(t) for _ in t.engines_y]
        self.master = True
        self.avionics = True
        self.alternator = True
        self.fuel_pump = False
        self.fuel_selector = 3       # 0 cerrado, 1 izq, 2 der, 3 ambos
        self.fuel_l = t.fuel_capacity * 0.75
        self.battery_charge = 1.0
        self.bus_volts = 28.0
        self.amps = 0.0
        self.vacuum = 5.0
        self.gyro_spin = 1.0         # 0..1 velocidad del giróscopo de vacío
        self.flaps_cmd = 0           # índice de posición
        self.flaps = 0.0             # grados actuales
        self.gear_down = True
        self.gear_pos = 1.0          # 0 arriba, 1 abajo
        self.lights = dict(nav=False, beacon=True, strobe=False, landing=False, taxi=False)
        self.pitot_heat = False
        self.failures = dict(engine=False, engine2=False, vacuum=False, pitot=False, static=False,
                             electrical=False, flaps=False, pfd=False, alternator=False,
                             fire=False, smoke=False, radio=False, gear=False, trim=False, door=False,
                             magneto=False, fuel_leak=False, carb_ice=False)
        self.carb_heat = False        # mando de calefacción al carburador (todos los motores)
        self.oat_c, self.dew_spread = 15.0, 8.0
        self.fire_level = 0.0
        self.smoke_level = 0.0
        self.trim_cb = True           # cortacircuito del compensador eléctrico
        self.gear_emergency = False   # palanca de extensión de emergencia del tren
        self.extinguisher = 1.0
        self.parking_brake = False
        self.stall_warning = False

    @property
    def engine(self):
        return self.engines[0]

    @property
    def twin(self):
        return len(self.engines) > 1

    @property
    def flap_target(self):
        return self.t.flap_settings[self.flaps_cmd]

    @property
    def electric_ok(self):
        return self.master and self.bus_volts > 20.0 and not self.failures["electrical"]

    @property
    def avionics_ok(self):
        return self.electric_ok and self.avionics

    def cold_and_dark(self):
        for e in self.engines:
            e.running = False
            e.rpm = 0.0
            e.pf = 0.0
            e.throttle = 0.0
            e.mixture = 0.0
            e.magnetos = 0
            e.carb_ice = 0.0
            e.oil_temp = 60.0
            e.cht = 60.0
            e.egt = 60.0
            e.oil_press = 0.0
        self.master = False
        self.avionics = False
        self.fuel_pump = False
        self.carb_heat = False
        self.parking_brake = True
        for k in self.lights:
            self.lights[k] = False
        self.gyro_spin = 0.0

    def ready_to_fly(self, airborne=False):
        self.master = True
        self.avionics = True
        self.carb_heat = False
        for e in self.engines:
            e.magnetos = 3
            e.mixture = 1.0
            e.carb_ice = 0.0
            e.set_running(True)
        self.gyro_spin = 1.0
        self.lights.update(nav=True, beacon=True, strobe=airborne, landing=not airborne)

    def update(self, dt, rho, p_amb, V, on_ground):
        t = self.t
        e = self.engine
        for i, en in enumerate(self.engines):
            en.failed = self.failures["engine" if i == 0 else "engine2"]
        fuel_ok = self.fuel_l > 0.1 and self.fuel_selector != 0
        # eléctrico
        alt_ok = (self.alternator and not self.failures["alternator"] and not self.failures["electrical"]
                  and any(en.running and en.rpm > 600 for en in self.engines) and self.master)
        load = 0.0
        if self.master:
            load += 3.0
            if self.avionics:
                load += 9.0
            load += sum((2.0 if k in ("landing", "taxi") else 0.8) for k, v in self.lights.items() if v)
            if self.fuel_pump:
                load += 2.0
            if self.pitot_heat:
                load += 5.0
            if any(en.starter for en in self.engines):
                load += 120.0
        if alt_ok:
            self.amps = 2.0 if self.battery_charge < 0.99 else 0.5
            self.battery_charge = min(1.0, self.battery_charge + dt / 1800.0)
            self.bus_volts = 28.0
        else:
            self.amps = -load if self.master else 0.0
            self.battery_charge = max(0.0, self.battery_charge - load * dt / (35.0 * 3600.0))
            self.bus_volts = (22.0 + 2.5 * self.battery_charge - (0.02 * load if any(en.starter for en in self.engines) else 0.0)) if self.master else 0.0
        if self.failures["electrical"]:
            self.bus_volts = 0.0
        battery_ok = self.master and self.battery_charge > 0.05 and not self.failures["electrical"]
        burned = 0.0
        for en in self.engines:
            if not battery_ok:
                en.starter = False
            en.carb_heat, en.force_ice = self.carb_heat, self.failures["carb_ice"]
            en.oat_c, en.dew_spread = self.oat_c, self.dew_spread
            burned += en.update(dt, rho, p_amb, V, fuel_ok, battery_ok)
        self.fuel_l = max(0.0, self.fuel_l - burned)

        # vacío y giróscopos
        if self.failures["vacuum"]:
            self.vacuum = approach(self.vacuum, 0.0, dt * 2.0)
        else:
            # bomba de vacío: ~4,3 inHg ya al ralentí (700 RPM) y hasta ~5,2 a plena potencia
            rpm = max(en.rpm for en in self.engines)
            self.vacuum = clamp(rpm / 700.0 * 4.3 if rpm < 700 else 4.3 + (rpm - 700) / 1600.0 * 0.9, 0.0, 5.2)
        target = clamp((self.vacuum - 2.5) / 1.6, 0.0, 1.0)
        rate = dt / 8.0 if target > self.gyro_spin else dt / 240.0
        self.gyro_spin = approach(self.gyro_spin, target, rate)

        # flaps (eléctricos)
        if self.electric_ok and not self.failures["flaps"]:
            self.flaps = approach(self.flaps, self.flap_target, t.flap_rate * dt)
        # tren retráctil (hidráulico/eléctrico)
        if t.retractable and self.gear_emergency:
            self.gear_pos = approach(self.gear_pos, 1.0, dt / 4.0)        # caída libre por gravedad
        elif t.retractable and self.electric_ok and not self.failures["gear"]:
            target = 1.0 if self.gear_down else 0.0
            self.gear_pos = approach(self.gear_pos, target, dt / 6.0)
        if not t.retractable:
            self.gear_pos = 1.0
        return burned

    @property
    def mass(self):
        return self.t.empty_mass + self.t.payload + self.fuel_l * self.t.fuel_density
