# predictor.py - Predictor PRO COMPLETO v3.3 (onefile ready)
# - Licencia blindada
# - Análisis unificado de RUPTURAS (gusanos + alternancias)
# - Pronóstico estadístico + IA Gemini
# - FIX: checkbox IA OFF = apuesta inmediata (IA solo informativa)
# - FIX: log ya no se congela
# - Soporte --onefile: datos junto al .exe
# Ejecuta: python predictor.py

import os
import sys
import time
import json
import re
import hashlib
import uuid
import platform
import subprocess
import threading
import webbrowser
import random
import tempfile
from datetime import datetime, timedelta
from collections import deque, Counter
from pathlib import Path

# ============================================================
# ============ BASE DIR (soporte onefile) ============
# ============================================================
# Detectar si corre como .exe empaquetado o como .py normal
# y forzar que todos los datos se guarden junto al ejecutable
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Forzar working directory a la carpeta del .exe / .py
try:
    os.chdir(BASE_DIR)
except Exception:
    pass

import requests
from flask import Flask, render_template_string, jsonify, request
from flask_cors import CORS

# ============================================================
# ============ CONFIG ============
# ============================================================
GEMINI_API_KEY = "AQ.Ab8RN6Lf01L8Wmx24M14uQ5EM_fswGvehmhPxK6IYOju-J-gmA"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
GEMINI_MODEL = "gemini-3.8-flash"

ALTERNANCIA_LARGA_UMBRAL = 6
DATA_DIR = os.path.join(BASE_DIR, "predictor_data")
PATRON_UMBRAL_VENTAJA = 58
PATRON_MIN_CASOS = 5
TIRADAS_POST_RUPTURA = 3


# ============================================================
# ============ LICENCIA ============
# ============================================================

class LicenseManager:
    def __init__(self):
        self.hwid = self.get_or_create_hwid()
        self.licencia_file = os.path.join(BASE_DIR, "licencia.lic")
        self.secret = "PREDICTOR_SECRET_2026_TRIAL_V2"
        self.trial_duration_hours = 24
        self.validated = False
        self.license_data = None
        self.is_trial = False
        self._trial_cache = None
        self.trial_paths = self._get_trial_paths()
        self.hwid_paths = self._get_hwid_paths()
        for p in self.trial_paths + self.hwid_paths:
            try:
                d = os.path.dirname(p)
                if d: os.makedirs(d, exist_ok=True)
            except: pass

    def _get_hwid_paths(self):
        paths = [
            os.path.join(BASE_DIR, "hwid.txt"),
            os.path.join(BASE_DIR, "predictor_data", ".hwid"),
            os.path.join(BASE_DIR, "predictor_data", ".cache", ".hwid"),
        ]
        try: paths.append(os.path.join(os.path.expanduser("~"), ".predictor_pro", ".hwid"))
        except: pass
        try: paths.append(os.path.join(tempfile.gettempdir(), ".predictor_pro_hwid"))
        except: pass
        return paths

    def _get_trial_paths(self):
        paths = [
            os.path.join(BASE_DIR, "trial.json"),
            os.path.join(BASE_DIR, "predictor_data", ".trial_backup"),
            os.path.join(BASE_DIR, "predictor_data", ".cache", ".trial_lock"),
        ]
        try: paths.append(os.path.join(os.path.expanduser("~"), ".predictor_pro", ".trial_lock"))
        except: pass
        try: paths.append(os.path.join(tempfile.gettempdir(), ".predictor_pro_trial"))
        except: pass
        return paths

    def _get_stats_path(self):
        return os.path.join(BASE_DIR, "predictor_data", "stats_global.json")

    def _firmar_trial(self, hwid, start_iso, expiry_iso):
        return hashlib.sha256(f"{hwid}|{start_iso}|{expiry_iso}|{self.secret}".encode()).hexdigest()

    def _validar_firma(self, data):
        if not isinstance(data, dict): return False
        return self._firmar_trial(data.get('hwid',''), data.get('start',''), data.get('expiry','')) == data.get('firma','')

    def _leer_archivo_trial(self, ruta):
        if not os.path.exists(ruta): return None
        try:
            with open(ruta, 'r', encoding='utf-8') as f: data = json.load(f)
            if not self._validar_firma(data): return None
            return data
        except: return None

    def _guardar_trial_en_todos(self, data):
        for ruta in self.trial_paths:
            try:
                d = os.path.dirname(ruta)
                if d: os.makedirs(d, exist_ok=True)
                with open(ruta, 'w', encoding='utf-8') as f: json.dump(data, f, indent=2)
            except: pass
        try:
            sp = self._get_stats_path()
            os.makedirs(os.path.dirname(sp), exist_ok=True)
            stats = {}
            if os.path.exists(sp):
                try:
                    with open(sp, 'r', encoding='utf-8') as f: stats = json.load(f)
                except: stats = {}
            stats['trial_info'] = data
            stats['trial_usado'] = True
            with open(sp, 'w', encoding='utf-8') as f: json.dump(stats, f, indent=2)
        except: pass

    def _buscar_trial_guardado(self):
        if self._trial_cache is not None: return self._trial_cache
        candidatos = []
        for ruta in self.trial_paths:
            d = self._leer_archivo_trial(ruta)
            if d: candidatos.append(d)
        sp = self._get_stats_path()
        if os.path.exists(sp):
            try:
                with open(sp, 'r', encoding='utf-8') as f: stats = json.load(f)
                t = stats.get('trial_info')
                if t and self._validar_firma(t): candidatos.append(t)
            except: pass
        if not candidatos: return None
        def get_start(c):
            try: return datetime.fromisoformat(c.get('start', '9999'))
            except: return datetime(9999, 1, 1)
        candidatos.sort(key=get_start)
        elegido = candidatos[0]
        self._trial_cache = elegido
        return elegido

    def get_or_create_hwid(self):
        for ruta in self._get_hwid_paths():
            if os.path.exists(ruta):
                try:
                    with open(ruta, 'r') as f:
                        hwid = f.read().strip()
                        if hwid and len(hwid) == 64: return hwid
                except: pass
        hwid = self.generar_hwid()
        for ruta in self._get_hwid_paths():
            try:
                d = os.path.dirname(ruta)
                if d: os.makedirs(d, exist_ok=True)
                with open(ruta, 'w') as f: f.write(hwid)
            except: pass
        return hwid

    def generar_hwid(self):
        try:
            data = [str(uuid.getnode()), platform.node()]
            if platform.system() == "Windows":
                try:
                    r = subprocess.check_output("wmic diskdrive get serialnumber", shell=True)
                    data.append(r.decode().split()[-1])
                except: pass
            data.extend([platform.system(), platform.release()])
            return hashlib.sha256("".join(data).encode()).hexdigest()
        except: return str(uuid.uuid4())

    def activar_trial(self):
        existente = self._buscar_trial_guardado()
        if existente:
            if existente.get('hwid') != self.hwid:
                return False, "⛔ La prueba ya fue usada en otro dispositivo"
            try:
                expiry = datetime.fromisoformat(existente.get('expiry', ''))
                if expiry < datetime.now():
                    return False, "⛔ Tu prueba gratuita ya expiró.\n\n📱 Contacta a soporte."
                else:
                    self.is_trial = True; self.validated = True; self.license_data = existente
                    hours_left = int((expiry - datetime.now()).total_seconds() / 3600)
                    return True, f"Prueba activa - {hours_left}h restantes"
            except: return False, "Error al verificar prueba"
        try:
            now = datetime.now()
            expiry = now + timedelta(hours=self.trial_duration_hours)
            data = {"hwid": self.hwid, "start": now.isoformat(), "expiry": expiry.isoformat(),
                    "usado": True, "trial": True}
            data['firma'] = self._firmar_trial(self.hwid, data['start'], data['expiry'])
            self._guardar_trial_en_todos(data)
            self._trial_cache = data
            self.is_trial = True; self.validated = True; self.license_data = data
            return True, f"✅ Prueba activada por {self.trial_duration_hours}h"
        except Exception as e: return False, f"Error: {str(e)}"

    def check_trial(self):
        data = self._buscar_trial_guardado()
        if not data: return False, "Sin prueba activa"
        if data.get('hwid') != self.hwid: return False, "Prueba de otro dispositivo"
        try:
            expiry = datetime.fromisoformat(data.get('expiry', ''))
            if expiry < datetime.now(): return False, "Prueba expirada"
            self.is_trial = True; self.validated = True; self.license_data = data
            hours_left = int((expiry - datetime.now()).total_seconds() / 3600)
            return True, f"Prueba activa - {hours_left}h restantes"
        except: return False, "Error al verificar prueba"

    def check_activation(self):
        if os.path.exists(self.licencia_file):
            try:
                with open(self.licencia_file) as f: lic = json.load(f)
                if lic.get('hwid') != self.hwid: return False, "Licencia de otro dispositivo"
                data = f"{lic['hwid']}{lic['expiry']}{lic['id']}{self.secret}"
                if hashlib.sha256(data.encode()).hexdigest() != lic.get('hash'):
                    return False, "Licencia corrupta"
                expiry = lic.get('expiry', '')
                if expiry != "9999-12-31":
                    if datetime.strptime(expiry, "%Y-%m-%d") < datetime.now():
                        return False, f"Licencia expirada {expiry}"
                self.validated = True; self.license_data = lic; self.is_trial = False
                return True, f"Licencia valida - {lic.get('duracion', '')}"
            except: pass
        return self.check_trial()

    def cargar_licencia(self, contenido):
        try:
            with open(self.licencia_file, 'w') as f: f.write(contenido)
            valid, msg = self.check_activation()
            if valid: return True, msg
            if os.path.exists(self.licencia_file): os.remove(self.licencia_file)
            return False, msg
        except Exception as e: return False, f"Error: {str(e)}"

    def get_hwid(self): return self.hwid

    def get_info(self):
        if self.is_trial and self.license_data:
            try:
                exp = datetime.fromisoformat(self.license_data.get('expiry', ''))
                return f"Trial {int((exp - datetime.now()).total_seconds()/3600)}h"
            except: return "Trial"
        if not self.license_data: return "No activado"
        expiry = self.license_data.get('expiry', '')
        duracion = self.license_data.get('duracion', '')
        if expiry == '9999-12-31': return "Permanente"
        try:
            exp = datetime.strptime(expiry, "%Y-%m-%d")
            days = (exp - datetime.now()).days
            return f"{duracion} - {days}d restantes" if days >= 0 else "Expirada"
        except: return duracion

    def is_valid(self):
        if self.validated and self.license_data:
            if self.is_trial:
                try: return datetime.fromisoformat(self.license_data.get('expiry','')) > datetime.now()
                except: return False
            expiry = self.license_data.get('expiry', '')
            if expiry == "9999-12-31": return True
            try: return datetime.strptime(expiry, "%Y-%m-%d") > datetime.now()
            except: pass
        return False


# ============================================================
# ============ ANALIZADOR DE RUPTURAS ============
# ============================================================

class AnalizadorRupturas:
    def __init__(self, historial_ref):
        self.historial = historial_ref
        self.cache = None
        self.cache_ts = 0
        self.cache_ttl = 45

    def detectar_patron_actual(self, colores):
        if not colores or len(colores) < 4:
            return None
        ultimo = colores[-1]
        racha = 0
        for c in reversed(colores):
            if c == ultimo: racha += 1
            else: break
        cambios = 0
        for i in range(len(colores)-1, 0, -1):
            if colores[i] != colores[i-1]: cambios += 1
            else: break
        if racha >= 3 and racha >= cambios:
            if 3 <= racha <= 4: subtipo = 'corto'
            elif racha == 5: subtipo = 'medio'
            else: subtipo = 'largo'
            return {
                'tipo': 'GUSANO', 'subtipo': subtipo, 'tamano': racha,
                'color_dominante': ultimo, 'colores_ventana': colores[-racha:],
            }
        elif cambios >= 3:
            if 3 <= cambios <= 5: subtipo = 'corta'
            else: subtipo = 'larga'
            return {
                'tipo': 'ALTERNANCIA', 'subtipo': subtipo, 'tamano': cambios,
                'color_dominante': None, 'colores_ventana': colores[-cambios-1:],
            }
        return None

    def detectar_ruptura(self, colores):
        if not colores or len(colores) < 5: return None
        ultimo = colores[-1]
        penultimo = colores[-2]
        if penultimo == ultimo: return None
        racha_previa = 0
        for i in range(len(colores)-2, -1, -1):
            if colores[i] == penultimo: racha_previa += 1
            else: break
        if racha_previa >= 3:
            if 3 <= racha_previa <= 4: subtipo = 'corto'
            elif racha_previa == 5: subtipo = 'medio'
            else: subtipo = 'largo'
            return {
                'tipo_roto': 'GUSANO', 'subtipo_roto': subtipo,
                'tamano_roto': racha_previa, 'color_roto': penultimo,
                'color_ruptor': ultimo,
            }
        cambios_previos = 0
        for i in range(len(colores)-2, 0, -1):
            if colores[i] != colores[i-1]: cambios_previos += 1
            else: break
        if cambios_previos >= 3:
            if 3 <= cambios_previos <= 5: subtipo = 'corta'
            else: subtipo = 'larga'
            return {
                'tipo_roto': 'ALTERNANCIA', 'subtipo_roto': subtipo,
                'tamano_roto': cambios_previos, 'color_roto': None,
                'color_ruptor': ultimo,
            }
        return None

    def buscar_rupturas_similares(self, tipo_roto, subtipo_roto):
        todos = self.historial._cargar_todos_colores()
        if len(todos) < 15: return None
        casos = 0
        categorias = {'nueva_racha_ruptor': 0, 'rebote_original': 0,
                       'alternancia_post': 0, 'mixto': 0}
        sig_counter = {'red': 0, 'blue': 0}
        i = 0
        while i < len(todos) - TIRADAS_POST_RUPTURA - 2:
            if i < 3:
                i += 1; continue
            if todos[i] == todos[i-1]:
                i += 1; continue
            racha_pre = 0
            for k in range(i-1, -1, -1):
                if todos[k] == todos[i-1]: racha_pre += 1
                else: break
            cambios_pre = 0
            for k in range(i-1, 0, -1):
                if todos[k] != todos[k-1]: cambios_pre += 1
                else: break
            match = False
            if tipo_roto == 'GUSANO':
                if racha_pre >= 3:
                    if subtipo_roto == 'corto' and 3 <= racha_pre <= 4: match = True
                    elif subtipo_roto == 'medio' and racha_pre == 5: match = True
                    elif subtipo_roto == 'largo' and racha_pre >= 6: match = True
            elif tipo_roto == 'ALTERNANCIA':
                if cambios_pre >= 3:
                    if subtipo_roto == 'corta' and 3 <= cambios_pre <= 5: match = True
                    elif subtipo_roto == 'larga' and cambios_pre >= 6: match = True
            if not match:
                i += 1; continue
            if i + TIRADAS_POST_RUPTURA > len(todos):
                i += 1; continue
            color_ruptor = todos[i]
            color_original = todos[i-1]
            post = todos[i:i+TIRADAS_POST_RUPTURA]
            if len(post) >= 3:
                if post[0] == post[1] == post[2] == color_ruptor: cat = 'nueva_racha_ruptor'
                elif post[0] == post[1] == post[2] == color_original: cat = 'rebote_original'
                elif post[0] != post[1] and post[1] != post[2]: cat = 'alternancia_post'
                else: cat = 'mixto'
            else:
                cat = 'mixto'
            categorias[cat] += 1
            if post:
                sig_counter[post[0]] += 1
                casos += 1
            i += 1
        if casos < PATRON_MIN_CASOS:
            return {'casos': casos, 'categorias': categorias, 'proxima_pred': None,
                    'proxima_conf': 0, 'sig_pct': {'red': 0, 'blue': 0}, 'insuficiente': True}
        total_sig = sig_counter['red'] + sig_counter['blue']
        pred = 'red' if sig_counter['red'] >= sig_counter['blue'] else 'blue'
        conf = round(max(sig_counter['red'], sig_counter['blue']) / total_sig * 100, 1)
        sig_pct = {
            'red': round(sig_counter['red'] / total_sig * 100, 1),
            'blue': round(sig_counter['blue'] / total_sig * 100, 1)
        }
        return {'casos': casos, 'categorias': categorias, 'proxima_pred': pred,
                'proxima_conf': conf, 'sig_pct': sig_pct, 'insuficiente': False}

    def generar_pronostico(self, colores):
        patron = self.detectar_patron_actual(colores)
        ruptura = self.detectar_ruptura(colores)
        detalles = {'patron_actual': patron, 'ruptura': None, 'similar': None, 'tendencia': None}
        tendencia = self._calcular_tendencia(colores)
        detalles['tendencia'] = tendencia
        if ruptura:
            detalles['ruptura'] = ruptura
            similar = self.buscar_rupturas_similares(ruptura['tipo_roto'], ruptura['subtipo_roto'])
            detalles['similar'] = similar
            if similar and not similar.get('insuficiente'):
                pred_rup = similar['proxima_pred']
                conf_rup = similar['proxima_conf']
                razon = (f"Ruptura {ruptura['tipo_roto']} {ruptura['subtipo_roto']} → "
                         f"{similar['casos']} casos, {pred_rup.upper()} en {conf_rup}%")
                if tendencia and tendencia['pred'] == pred_rup:
                    conf_final = min(conf_rup + 5, 95)
                    razon += " (+ tendencia)"
                else: conf_final = conf_rup
                return {'pred': pred_rup, 'conf': conf_final, 'razon': razon, 'detalles': detalles}
            else:
                return {'pred': None, 'conf': 0,
                        'razon': f"Ruptura {ruptura['tipo_roto']} {ruptura['subtipo_roto']} sin datos",
                        'detalles': detalles}
        if patron:
            if patron['tipo'] == 'GUSANO':
                pred = patron['color_dominante']
                if patron['subtipo'] == 'largo': conf = 75
                elif patron['subtipo'] == 'medio': conf = 70
                else: conf = 65
                razon = f"Gusano {patron['subtipo']} de {patron['tamano']} → seguir {pred.upper()} ({conf}%)"
                return {'pred': pred, 'conf': conf, 'razon': razon, 'detalles': detalles}
            elif patron['tipo'] == 'ALTERNANCIA':
                ultimo = colores[-1]
                pred = 'blue' if ultimo == 'red' else 'red'
                conf = 70 if patron['subtipo'] == 'larga' else 65
                razon = f"Alternancia {patron['subtipo']} ({patron['tamano']}) → opuesto {pred.upper()} ({conf}%)"
                return {'pred': pred, 'conf': conf, 'razon': razon, 'detalles': detalles}
        if tendencia and tendencia['pred']:
            return {'pred': tendencia['pred'], 'conf': tendencia['conf'],
                    'razon': tendencia['razon'], 'detalles': detalles}
        return {'pred': None, 'conf': 0, 'razon': "Sin patrón claro", 'detalles': detalles}

    def _calcular_tendencia(self, colores):
        if len(colores) < 5: return None
        ultimos = colores[-20:]
        c = Counter(ultimos)
        total = len(ultimos)
        pct_r = round(c['red'] / total * 100, 1)
        pct_b = round(c['blue'] / total * 100, 1)
        if pct_r >= 55: return {'pred': 'red', 'conf': pct_r, 'razon': f"Tendencia R ({pct_r}%)"}
        elif pct_b >= 55: return {'pred': 'blue', 'conf': pct_b, 'razon': f"Tendencia B ({pct_b}%)"}
        return {'pred': None, 'conf': 0, 'razon': f"Sin tendencia (R {pct_r}% / B {pct_b}%)"}

    def analizar_todas_rupturas(self, forzar=False):
        ahora = time.time()
        if not forzar and self.cache and (ahora - self.cache_ts) < self.cache_ttl:
            return self.cache
        colores = self.historial._cargar_todos_colores()
        total = len(colores)
        if total < 15:
            self.cache = {'total_datos': total, 'mensaje': 'Datos insuficientes', 'grupos': []}
            self.cache_ts = ahora
            return self.cache
        grupos = []
        for subtipo, label in [('corto', 'Gusano corto (3-4)'),
                                ('medio', 'Gusano medio (5)'),
                                ('largo', 'Gusano largo (6+)')]:
            r = self.buscar_rupturas_similares('GUSANO', subtipo)
            if r and not r.get('insuficiente'):
                grupos.append({'nombre': label, 'tipo': 'GUSANO', 'subtipo': subtipo,
                               'casos': r['casos'], 'categorias': r['categorias'],
                               'proxima_pred': r['proxima_pred'], 'proxima_conf': r['proxima_conf'],
                               'sig_pct': r['sig_pct']})
        for subtipo, label in [('corta', 'Alternancia corta (3-5)'),
                                ('larga', 'Alternancia larga (6+)')]:
            r = self.buscar_rupturas_similares('ALTERNANCIA', subtipo)
            if r and not r.get('insuficiente'):
                grupos.append({'nombre': label, 'tipo': 'ALTERNANCIA', 'subtipo': subtipo,
                               'casos': r['casos'], 'categorias': r['categorias'],
                               'proxima_pred': r['proxima_pred'], 'proxima_conf': r['proxima_conf'],
                               'sig_pct': r['sig_pct']})
        contador = Counter(colores)
        pct_r = round(contador['red'] / total * 100, 1)
        pct_b = round(contador['blue'] / total * 100, 1)
        grupos.append({'nombre': 'Frecuencia global', 'tipo': 'FRECUENCIA', 'casos': total,
                       'descripcion': f"R: {contador['red']} ({pct_r}%) | B: {contador['blue']} ({pct_b}%)"})
        self.cache = {'total_datos': total, 'fecha_analisis': datetime.now().strftime("%H:%M:%S"),
                      'grupos': grupos}
        self.cache_ts = ahora
        return self.cache

    def construir_contexto_ia(self, colores, pronostico):
        partes = []
        partes.append("=== CONTEXTO ===")
        partes.append(f"Últimos {len(colores[-20:])} colores: " + " ".join(c.upper()[0] for c in colores[-20:]))
        partes.append("")
        pat = pronostico['detalles'].get('patron_actual')
        if pat:
            if pat['tipo'] == 'GUSANO':
                partes.append(f"PATRÓN: GUSANO {pat['subtipo']} de {pat['tamano']} {pat['color_dominante'].upper()}")
            elif pat['tipo'] == 'ALTERNANCIA':
                partes.append(f"PATRÓN: ALTERNANCIA {pat['subtipo']} de {pat['tamano']} cambios")
        rup = pronostico['detalles'].get('ruptura')
        if rup:
            partes.append(f"⚠️ RUPTURA: {rup['tipo_roto']} {rup['subtipo_roto']} (tam {rup['tamano_roto']})")
            if rup['color_roto']: partes.append(f"   Original: {rup['color_roto'].upper()}")
            partes.append(f"   Ruptor: {rup['color_ruptor'].upper()}")
        sim = pronostico['detalles'].get('similar')
        if sim and not sim.get('insuficiente'):
            partes.append(f"CASOS SIMILARES: {sim['casos']}")
            c = sim['categorias']
            partes.append(f"   Nueva racha ruptor: {c['nueva_racha_ruptor']}")
            partes.append(f"   Rebote original:    {c['rebote_original']}")
            partes.append(f"   Alternancia post:   {c['alternancia_post']}")
            partes.append(f"   Mixto:              {c['mixto']}")
            partes.append(f"   → Próxima: {sim['proxima_pred'].upper()} ({sim['proxima_conf']}%)")
        tend = pronostico['detalles'].get('tendencia')
        if tend: partes.append(f"TENDENCIA: {tend['razon']}")
        partes.append("")
        partes.append(f"PRONÓSTICO MATE: {pronostico['pred']} ({pronostico['conf']}%)")
        partes.append("Analiza y responde con tu predicción.")
        return "\n".join(partes)


# ============================================================
# ============ HISTORIAL ============
# ============================================================

class HistorialManager:
    def __init__(self, data_dir=None):
        if data_dir is None: data_dir = DATA_DIR
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)
        self.hoy = datetime.now().strftime("%Y-%m-%d")
        self.archivo_hoy = self.data_dir / f"{self.hoy}.json"
        self.archivo_stats = self.data_dir / "stats_global.json"
        self.dia_actual = self._cargar_o_crear_dia()
        self.stats_global = self._cargar_stats_global()
        self._cache_todos_colores = None
        self._cache_todos_colores_ts = 0

    def _cargar_o_crear_dia(self):
        if self.archivo_hoy.exists():
            try:
                with open(self.archivo_hoy, 'r', encoding='utf-8') as f: return json.load(f)
            except: pass
        return {"fecha": self.hoy, "colores": [], "predicciones": []}

    def _cargar_stats_global(self):
        if self.archivo_stats.exists():
            try:
                with open(self.archivo_stats, 'r', encoding='utf-8') as f: return json.load(f)
            except: pass
        return {
            "total_colores": 0, "total_predicciones": 0,
            "mate_wins": 0, "mate_losses": 0,
            "ia_wins": 0, "ia_losses": 0,
            "por_modo": {"TENDENCIA": {"wins":0,"losses":0},
                         "ALTERNANCIA": {"wins":0,"losses":0},
                         "OPUESTO": {"wins":0,"losses":0}},
            "transiciones": {"R->R":0, "R->B":0, "B->B":0, "B->R":0},
            "ultima_actualizacion": datetime.now().isoformat()
        }

    def _guardar_dia(self):
        try:
            with open(self.archivo_hoy, 'w', encoding='utf-8') as f:
                json.dump(self.dia_actual, f, indent=2, ensure_ascii=False)
        except Exception as e: print(f"[Historial] Error: {e}")

    def _guardar_stats(self):
        try:
            self.stats_global["ultima_actualizacion"] = datetime.now().isoformat()
            with open(self.archivo_stats, 'w', encoding='utf-8') as f:
                json.dump(self.stats_global, f, indent=2, ensure_ascii=False)
        except: pass

    def registrar_color(self, color):
        self.dia_actual["colores"].append({
            "hora": datetime.now().strftime("%H:%M:%S"),
            "color": color
        })
        self.stats_global["total_colores"] = self.stats_global.get("total_colores", 0) + 1
        colores_hoy = [c["color"] for c in self.dia_actual["colores"]]
        if len(colores_hoy) >= 2:
            key = f"{colores_hoy[-2][0].upper()}->{colores_hoy[-1][0].upper()}"
            if key in self.stats_global.get("transiciones", {}):
                self.stats_global["transiciones"][key] += 1
        self._guardar_dia()
        self._cache_todos_colores = None

    def registrar_prediccion(self, pred_mate, modo, pred_ia, conf_ia, razon_ia, resultado):
        mate_ok = None; ia_ok = None
        if resultado in ['red', 'blue']:
            mate_short = pred_mate[0].upper() if pred_mate else None
            res_short = resultado[0].upper()
            mate_ok = (mate_short == res_short)
            if pred_ia and pred_ia in ['R', 'B']:
                ia_ok = (pred_ia == res_short)
        self.dia_actual["predicciones"].append({
            "hora": datetime.now().strftime("%H:%M:%S"),
            "pred_mate": pred_mate, "modo": modo,
            "pred_ia": pred_ia, "conf_ia": conf_ia, "razon_ia": razon_ia,
            "resultado": resultado, "mate_ok": mate_ok, "ia_ok": ia_ok
        })
        self.stats_global["total_predicciones"] = self.stats_global.get("total_predicciones", 0) + 1
        if mate_ok is True: self.stats_global["mate_wins"] = self.stats_global.get("mate_wins", 0) + 1
        elif mate_ok is False: self.stats_global["mate_losses"] = self.stats_global.get("mate_losses", 0) + 1
        if ia_ok is True: self.stats_global["ia_wins"] = self.stats_global.get("ia_wins", 0) + 1
        elif ia_ok is False: self.stats_global["ia_losses"] = self.stats_global.get("ia_losses", 0) + 1
        self._guardar_dia()
        self._guardar_stats()

    def _cargar_todos_colores(self):
        ahora = time.time()
        if self._cache_todos_colores is not None and (ahora - self._cache_todos_colores_ts) < 60:
            return self._cache_todos_colores
        todos = []
        for archivo in sorted(self.data_dir.glob("20*.json")):
            if archivo.name == "stats_global.json": continue
            try:
                with open(archivo, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    todos.extend([c["color"] for c in data.get("colores", [])])
            except: pass
        self._cache_todos_colores = todos
        self._cache_todos_colores_ts = ahora
        return todos

    def get_resumen(self, analizador):
        stats = analizador.analizar_todas_rupturas()
        return {
            'total_global': stats['total_datos'],
            'grupos': stats.get('grupos', []),
            'fecha_analisis': stats.get('fecha_analisis', ''),
            'stats_predictor': {
                'mate_wins': self.stats_global.get('mate_wins', 0),
                'mate_losses': self.stats_global.get('mate_losses', 0),
                'ia_wins': self.stats_global.get('ia_wins', 0),
                'ia_losses': self.stats_global.get('ia_losses', 0),
            }
        }


# ============================================================
# ============ GEMINI ============
# ============================================================

class GeminiAnalyst:
    def __init__(self, api_key=None):
        self.api_key = api_key or GEMINI_API_KEY
        self.last_analysis = None
        self.last_call_time = 0
        self.min_interval = 5
        self.enabled = bool(self.api_key and self.api_key.startswith("AQ."))
        self.analizando = False
        self.modelo = GEMINI_MODEL

    def analizar(self, colores, contexto):
        if not self.enabled: return None
        if len(colores) < 5: return None
        now = time.time()
        if now - self.last_call_time < self.min_interval: return self.last_analysis
        if self.analizando: return self.last_analysis
        self.analizando = True; self.last_call_time = now
        try:
            secuencia = " ".join([c.upper()[0] for c in colores[-30:]])
            prompt = f"""Eres un analista experto en ruleta rojo/azul OTC.

Secuencia (R=Rojo, B=Azul):
{secuencia}

{contexto}

Responde ÚNICAMENTE con JSON:
{{"prediccion": "R" o "B" o "ESPERAR", "confianza": 0-100, "razonamiento": "una frase corta", "recomendacion": "APOSTAR" o "ESPERAR"}}"""
            payload = {
                "model": self.modelo, "input": prompt, "store": False,
                "response_format": {
                    "type": "text", "mime_type": "application/json",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "prediccion": {"type": "string", "enum": ["R", "B", "ESPERAR"]},
                            "confianza": {"type": "integer"},
                            "razonamiento": {"type": "string"},
                            "recomendacion": {"type": "string", "enum": ["APOSTAR", "ESPERAR"]}
                        },
                        "required": ["prediccion", "confianza", "razonamiento", "recomendacion"]
                    }
                }
            }
            headers = {"Content-Type": "application/json", "x-goog-api-key": self.api_key}
            r = None
            for intento in range(3):
                try:
                    r = requests.post(GEMINI_URL, json=payload, headers=headers, timeout=30)
                    if r.status_code == 200: break
                    elif r.status_code == 503: time.sleep(3 * (intento + 1))
                    else: break
                except: time.sleep(2)
            if not r or r.status_code != 200: return self.last_analysis
            data = r.json()
            texto = None
            try:
                for step in data.get("steps", []):
                    if step.get("type") == "model_output":
                        for content in step.get("content", []):
                            if content.get("type") == "text":
                                texto = content.get("text", ""); break
                    if texto: break
            except: return self.last_analysis
            if not texto: return self.last_analysis
            texto = texto.strip()
            texto = re.sub(r'^```json\s*', '', texto)
            texto = re.sub(r'\s*```$', '', texto).strip()
            try: analysis = json.loads(texto)
            except json.JSONDecodeError:
                match = re.search(r'\{[^{}]*\}', texto)
                if match: analysis = json.loads(match.group())
                else: return self.last_analysis
            if 'prediccion' not in analysis: return self.last_analysis
            analysis['timestamp'] = time.strftime("%H:%M:%S")
            self.last_analysis = analysis
            return analysis
        except: return self.last_analysis
        finally: self.analizando = False

    def get_analysis(self): return self.last_analysis


# ============================================================
# ============ PREDICTOR ============
# ============================================================

class TrendFollowerPredictor:
    def __init__(self):
        self.reset_session()

    def reset_session(self):
        self.session_history = deque(maxlen=50)
        self.last_prediction = None
        self.consecutive_losses = 0
        self.max_losses = 3
        self.modo_alternancia = False
        self.alternancia_len = 0
        self.esperando_opuesto = False
        self.ultima_logica = ""

    def process_color(self, new_color):
        if new_color not in ['red', 'blue']: return
        self.session_history.append(new_color)

    def update_prediction(self, actual_color):
        was_correct = self.last_prediction == actual_color
        if was_correct:
            self.consecutive_losses = 0
            if self.modo_alternancia: self.alternancia_len += 1
            if self.esperando_opuesto:
                self.esperando_opuesto = False
                self.modo_alternancia = False
                self.alternancia_len = 0
        else:
            self.consecutive_losses += 1
            if self.consecutive_losses >= self.max_losses:
                if not self.modo_alternancia:
                    self.modo_alternancia = True
                    self.alternancia_len = 0
        return was_correct

    def get_prediction(self):
        if not self.session_history: return None, 0.0, "Esperando datos..."
        last_color = self.session_history[-1]
        opuesto = 'blue' if last_color == 'red' else 'red'
        if self.esperando_opuesto:
            self.ultima_logica = "opuesto_ruptura"
            return opuesto, 0.85, f"OPUESTO tras ruptura larga: {opuesto.upper()}"
        if self.modo_alternancia:
            self.ultima_logica = "alternancia"
            return opuesto, 0.80, f"ALTERNANCIA ({self.alternancia_len}) - Opuesto: {opuesto.upper()}"
        confidence = 0.75
        if len(self.session_history) >= 2:
            l2 = list(self.session_history)[-2:]
            if l2[0] == l2[1]: confidence = 0.85
            if len(self.session_history) >= 3:
                l3 = list(self.session_history)[-3:]
                if l3[0] == l3[1] == l3[2]: confidence = 0.92
        self.ultima_logica = "tendencia"
        logic = f"Seguir: {last_color.upper()} ({int(confidence*100)}%)"
        return last_color, confidence, logic

    def get_mode_info(self):
        if self.esperando_opuesto: return "OPUESTO"
        if self.modo_alternancia: return f"ALTERNANCIA ({self.alternancia_len})"
        if self.consecutive_losses > 0: return f"{self.consecutive_losses}/3 pérdidas"
        return "TENDENCIA"

    def get_state(self):
        return {
            'history': list(self.session_history),
            'consecutive_losses': self.consecutive_losses,
            'modo_alternancia': self.modo_alternancia,
            'last_prediction': self.last_prediction,
            'mode_info': self.get_mode_info(),
            'esperando_opuesto': self.esperando_opuesto,
            'last_colors': list(self.session_history)[-6:],
            'alternancia_len': self.alternancia_len,
        }


# ============================================================
# ============ BETTING ============
# ============================================================

class BettingAccount:
    def __init__(self, username, password, account_id):
        self.username = username
        self.password = password
        self.account_id = account_id
        self.base_url = "https://www.ff2016.vip/api"
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json",
                                       "User-Agent": "Mozilla/5.0 (Android 10; Mobile)"})
        self.token = None; self.device_id = None; self.balance = 0.0
        self.initial_bet = 0.1; self.current_bet = self.initial_bet
        self.max_consecutive_losses = 3; self.max_bet = 5.0
        self.consecutive_losses = 0; self.is_logged_in = False

    def login(self):
        self.device_id = ''.join(random.choices('0123456789', k=20))
        try:
            r = self.session.post(f"{self.base_url}/user/login?lang=es",
                json={"account": self.username, "password": self.password, "deviceId": self.device_id},
                timeout=10)
            data = r.json()
            if data.get("code") == 1:
                self.token = data["data"]["userinfo"]["token"]
                self.session.headers.update({"token": self.token})
                self.is_logged_in = True
                self.get_account_info()
                return True, f"OK {self.username}: ${self.balance:.2f}"
            return False, f"ERR {self.username}: {data.get('msg', 'Error')}"
        except Exception as e: return False, f"ERR {self.username}: {str(e)[:40]}"

    def get_account_info(self):
        if not self.token: return False, "Login first"
        try:
            r = self.session.post(f"{self.base_url}/user/get_user_info?lang=es",
                                   json={"deviceId": self.device_id})
            data = r.json()
            if data.get("code") == 1:
                self.balance = float(data["data"].get("money", 0.0))
                return True, self.balance
        except: pass
        return False, 0

    def place_bet(self, side, amount):
        if not self.token: return False, "Login first"
        try:
            bet_amount = round(float(amount), 2)
            if bet_amount < 0.1: return False, "Min 0.10"
            if bet_amount > self.max_bet: bet_amount = self.max_bet
        except: return False, "Invalid"
        try:
            r = self.session.post(f"{self.base_url}/game/add_bet?lang=es",
                json={"side": side.lower(), "money": bet_amount, "redeem_id": 0,
                      "deviceId": self.device_id})
            data = r.json()
            if data.get("code") == 1:
                self.get_account_info()
                return True, f"${bet_amount:.2f}"
            return False, data.get("msg", "Error")
        except: return False, "Connection error"

    def to_dict(self):
        return {'id': self.account_id, 'username': self.username,
                'balance': round(self.balance, 2),
                'current_bet': round(self.current_bet, 2),
                'is_logged_in': self.is_logged_in}


class BettingSystem:
    def __init__(self):
        self.accounts = []
        self.aggressive_sequence = [0.1, 0.2, 0.4, 0.8, 1.6, 3.2, 6.4]
        self.settings = {'initial_bet': 0.1, 'max_consecutive_losses': 3,
                         'max_bet': 5.0, 'martingale': False, 'aggressive': False}

    def add_account(self, username, password):
        if len(self.accounts) >= 3: return False, "Max 3 cuentas"
        for acc in self.accounts:
            if acc.username == username: return False, "Cuenta ya existe"
        self.accounts.append(BettingAccount(username, password, len(self.accounts) + 1))
        return True, f"Cuenta agregada: {username}"

    def remove_account(self, account_id):
        for i, acc in enumerate(self.accounts):
            if acc.account_id == account_id:
                removed = self.accounts.pop(i)
                for new_id, r in enumerate(self.accounts, 1): r.account_id = new_id
                return True, f"Cuenta eliminada: {removed.username}"
        return False, "Cuenta no encontrada"

    def login_all(self): return [a.login()[1] for a in self.accounts]
    def get_active_accounts(self): return [a for a in self.accounts if a.is_logged_in]

    def update_settings(self, settings):
        self.settings = settings
        for acc in self.accounts:
            acc.initial_bet = settings['initial_bet']; acc.current_bet = settings['initial_bet']
            acc.max_consecutive_losses = settings['max_consecutive_losses']
            acc.max_bet = settings['max_bet']

    def place_bet_all(self, side):
        results, total = [], 0
        for acc in self.get_active_accounts():
            if acc.balance >= acc.current_bet:
                ok, msg = acc.place_bet(side, acc.current_bet)
                if ok:
                    results.append(f"OK {acc.username}: ${acc.current_bet:.2f}")
                    total += acc.current_bet
                else: results.append(f"ERR {acc.username}: {msg}")
            else: results.append(f"ERR {acc.username}: Saldo bajo")
        return results, total

    def update_balances(self):
        for acc in self.accounts:
            if acc.is_logged_in: acc.get_account_info()

    def get_total_balance(self): return sum(a.balance for a in self.accounts if a.is_logged_in)

    def reset_bets_after_win(self):
        for acc in self.get_active_accounts():
            acc.current_bet = self.settings['initial_bet']; acc.consecutive_losses = 0

    def update_bets_after_loss(self):
        for acc in self.get_active_accounts():
            acc.consecutive_losses += 1
            if acc.consecutive_losses >= self.settings['max_consecutive_losses']:
                return False, f"Stop loss {acc.username}"
            if self.settings['martingale']:
                acc.current_bet = min(acc.current_bet * 2, self.settings['max_bet'])
            elif self.settings['aggressive']:
                lc = min(acc.consecutive_losses, len(self.aggressive_sequence) - 1)
                acc.current_bet = min(self.aggressive_sequence[lc], self.settings['max_bet'])
        return True, "Apuestas actualizadas"

    def get_state(self):
        return {'accounts': [a.to_dict() for a in self.accounts],
                'total_balance': round(self.get_total_balance(), 2),
                'settings': self.settings}


# ============================================================
# ============ FLASK + STATE ============
# ============================================================

app = Flask(__name__)
CORS(app)

license_mgr = LicenseManager()
predictor = TrendFollowerPredictor()
betting = BettingSystem()
historial = HistorialManager()
analizador = AnalizadorRupturas(historial)
analyst = GeminiAnalyst()

state = {
    'running': False, 'betting_active': False, 'wins': 0, 'losses': 0,
    'prediction_index': 0, 'logs': [], 'last_processed_index': 0,
    'last_color_time': datetime.now(),
    'ia_confirm_required': True, 'esperando_ia': False,
    'ultima_pred': None, 'ultima_ia': None, 'ultimo_modo': "",
    'pronostico_actual': None,
    'esperar_2_losses': False,
    'losses_seguidas': 0,
    'habilitado_apostar': False,
    'ia_fallo': False,
    '_log_counter': 0,
}

API_URL = "https://www.ff2016.vip/api/game/getchart?lang=es"
API_HEADERS = {"token": "81c635fe-0f6e-4bff-aede-4a69d9c9ef2d",
                "Content-Type": "application/json"}


def log(msg, color="normal"):
    ts = time.strftime("%H:%M:%S")
    state['_log_counter'] += 1
    state['logs'].append({
        'time': ts,
        'msg': msg,
        'color': color,
        'id': state['_log_counter']
    })
    if len(state['logs']) > 400: state['logs'] = state['logs'][-400:]
    print(f"[{ts}] {msg}")


# ============================================================
# ============ HTML (igual que antes, sin cambios) ============
# ============================================================

HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Predictor PRO</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
:root {
    --bg: #0a0e17; --card: #131825; --card2: #1a2130; --border: #2a3446;
    --accent: #00e5ff; --success: #00ff9d; --danger: #ff2e63;
    --warning: #ffb547; --info: #5eb3ff; --purple: #a855f7;
    --red: #ff3b5c; --blue: #3b82f6;
    --text: #f0f6fc; --text-dim: #8b98a9; --text-muted: #5a6478;
}
body { font-family: 'Segoe UI', system-ui, sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; }
#activationScreen { min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 20px;
    background: radial-gradient(circle at 20% 20%, rgba(0, 229, 255, 0.08) 0%, transparent 50%),
                radial-gradient(circle at 80% 80%, rgba(94, 179, 255, 0.08) 0%, transparent 50%), var(--bg); }
.activation-box { width: 100%; max-width: 480px; }
.activation-logo { text-align: center; margin-bottom: 30px; }
.activation-logo-icon { font-size: 64px; filter: drop-shadow(0 0 30px var(--accent)); display: inline-block; }
.activation-title { font-size: 34px; font-weight: 900; background: linear-gradient(135deg, var(--accent), var(--info)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; letter-spacing: 2px; margin-top: 12px; }
.activation-sub { font-size: 11px; color: var(--text-muted); letter-spacing: 4px; text-transform: uppercase; margin-top: 6px; }
.activation-card { background: var(--card); border: 1px solid var(--border); border-radius: 16px; padding: 22px; margin-bottom: 14px; }
.activation-card-title { display: flex; align-items: center; gap: 10px; font-size: 12px; font-weight: 800; text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 14px; color: var(--accent); }
.hwid-box { background: #0a0e17; border: 1.5px dashed var(--border); border-radius: 10px; padding: 14px; font-family: 'Consolas', monospace; font-size: 11px; color: var(--accent); word-break: break-all; line-height: 1.6; margin-bottom: 8px; cursor: pointer; text-align: center; user-select: all; }
.hwid-hint { font-size: 10px; color: var(--text-muted); text-align: center; }
.activation-status { text-align: center; padding: 16px; border-radius: 12px; background: var(--card2); margin-top: 8px; }
.activation-status-text { font-size: 16px; font-weight: 800; letter-spacing: 1px; text-transform: uppercase; }
.activation-status-text.success { color: var(--success); }
.activation-status-text.danger { color: var(--danger); }
.activation-status-text.warning { color: var(--warning); }
.activation-status-info { font-size: 11px; color: var(--text-dim); margin-top: 6px; }
.file-input-hidden { display: none; }
.file-label { display: block; width: 100%; padding: 14px; background: linear-gradient(135deg, var(--info), #3b82f6); color: white; text-align: center; border-radius: 10px; font-weight: 800; font-size: 13px; cursor: pointer; text-transform: uppercase; letter-spacing: 1px; }
.file-name { text-align: center; font-size: 11px; color: var(--success); margin-top: 10px; font-weight: 600; }
#dashboardScreen { display: none; }
.header { background: linear-gradient(90deg, #131825, #0a0e17); padding: 16px 24px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--border); position: sticky; top: 0; z-index: 100; }
.logo { display: flex; align-items: center; gap: 12px; }
.logo-icon { font-size: 28px; filter: drop-shadow(0 0 8px var(--accent)); }
.logo-text { font-size: 22px; font-weight: 800; background: linear-gradient(135deg, var(--accent), var(--info)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; letter-spacing: 1px; }
.logo-sub { font-size: 10px; color: var(--text-muted); letter-spacing: 3px; text-transform: uppercase; }
.header-right { display: flex; align-items: center; gap: 16px; }
.license-badge { padding: 6px 14px; background: var(--card2); border: 1px solid var(--border); border-radius: 20px; font-size: 11px; font-weight: 600; color: var(--success); }
.status-badge { display: flex; align-items: center; gap: 8px; padding: 6px 14px; background: var(--card2); border-radius: 20px; font-size: 12px; font-weight: 700; color: var(--text-muted); }
.status-badge.online { color: var(--success); }
.status-dot { width: 8px; height: 8px; border-radius: 50%; background: currentColor; }
.container { display: grid; grid-template-columns: 1fr 1.4fr; gap: 16px; padding: 20px; max-width: 1600px; margin: 0 auto; }
@media (max-width: 1024px) { .container { grid-template-columns: 1fr; padding: 12px; } }
.column { display: flex; flex-direction: column; gap: 16px; }
.card { background: var(--card); border: 1px solid var(--border); border-radius: 14px; padding: 20px; position: relative; }
.card.ai-card { border-color: rgba(168, 85, 247, 0.4); }
.card.ai-card .card-title { color: var(--purple); }
.card.patron-card { border-color: rgba(255, 181, 71, 0.4); }
.card.patron-card .card-title { color: var(--warning); }
.card.stats-card { border-color: rgba(0, 255, 157, 0.3); }
.card.stats-card .card-title { color: var(--success); }
.card-title { font-size: 12px; font-weight: 800; color: var(--accent); text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 16px; display: flex; align-items: center; justify-content: space-between; }
.stats-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
@media (max-width: 600px) { .stats-grid { grid-template-columns: repeat(2, 1fr); } }
.stat { background: var(--card2); padding: 14px 10px; border-radius: 10px; text-align: center; }
.stat-label { font-size: 9px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 6px; font-weight: 700; }
.stat-value { font-size: 24px; font-weight: 800; line-height: 1; }
.stat-value.success { color: var(--success); }
.stat-value.danger { color: var(--danger); }
.stat-value.warning { color: var(--warning); }
.stat-value.accent { color: var(--accent); }
.btn { border: none; border-radius: 10px; padding: 12px 20px; font-family: inherit; font-size: 13px; font-weight: 800; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; gap: 8px; text-transform: uppercase; letter-spacing: 0.5px; outline: none; }
.btn:disabled { opacity: 0.4; cursor: not-allowed; }
.btn-primary { background: linear-gradient(135deg, var(--accent), #0097b2); color: var(--bg); }
.btn-success { background: linear-gradient(135deg, var(--success), #00cc7d); color: var(--bg); }
.btn-danger { background: linear-gradient(135deg, var(--danger), #cc2450); color: white; }
.btn-ghost { background: var(--card2); color: var(--text-dim); border: 1px solid var(--border); }
.btn-lg { padding: 16px 24px; font-size: 14px; }
.btn-block { width: 100%; }
.btn-row { display: flex; gap: 10px; }
.btn-row > .btn { flex: 1; }
.input-label { display: block; font-size: 10px; color: var(--text-dim); text-transform: uppercase; letter-spacing: 1px; margin-bottom: 6px; font-weight: 700; }
.input { width: 100%; background: #0a0e17; border: 1.5px solid var(--border); border-radius: 10px; padding: 12px 14px; font-family: inherit; font-size: 13px; color: var(--text); outline: none; }
.input:focus { border-color: var(--accent); }
.input-row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 12px; }
.prediction-display { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin: 16px 0; }
@media (max-width: 600px) { .prediction-display { grid-template-columns: 1fr 1fr; } .prediction-display > :last-child { grid-column: 1 / -1; } }
.pred-box { background: var(--card2); padding: 20px 10px; border-radius: 12px; text-align: center; border: 2px solid var(--border); }
.pred-box-label { font-size: 9px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 8px; font-weight: 700; }
.pred-box-value { font-size: 32px; font-weight: 900; line-height: 1; color: var(--text-muted); }
.pred-box-value.red { color: var(--red); }
.pred-box-value.blue { color: var(--blue); }
.pred-box-value.purple { color: var(--purple); }
.pred-box-value.wait { color: var(--warning); }
.last6-grid { display: flex; gap: 6px; justify-content: center; flex-wrap: wrap; }
.last6-dot { width: 28px; height: 28px; border-radius: 50%; border: 2px solid var(--border); background: var(--card2); }
.last6-dot.red { background: var(--red); border-color: var(--red); }
.last6-dot.blue { background: var(--blue); border-color: var(--blue); }
.confidence-bar { background: var(--card2); border-radius: 10px; height: 8px; overflow: hidden; margin-top: 12px; }
.confidence-fill { height: 100%; background: linear-gradient(90deg, var(--info), var(--accent)); border-radius: 10px; transition: width 0.5s; }
.confidence-fill.purple { background: linear-gradient(90deg, var(--info), var(--purple)); }
.logic-box { background: var(--card2); padding: 12px 16px; border-radius: 10px; font-size: 12px; color: var(--text-dim); border-left: 3px solid var(--accent); margin-top: 12px; font-family: 'Consolas', monospace; }
.logic-box.purple { border-left-color: var(--purple); font-family: 'Segoe UI', sans-serif; }
.logic-box.warning { border-left-color: var(--warning); font-family: 'Segoe UI', sans-serif; }
.ai-coincide-badge { display: inline-block; padding: 4px 12px; border-radius: 20px; font-size: 10px; font-weight: 800; letter-spacing: 1px; text-transform: uppercase; }
.ai-coincide-badge.match { background: rgba(0,255,157,0.15); color: var(--success); }
.ai-coincide-badge.diff { background: rgba(255,46,99,0.15); color: var(--danger); }
.ai-coincide-badge.wait { background: rgba(255,181,71,0.15); color: var(--warning); }
.account-row { display: flex; align-items: center; justify-content: space-between; padding: 10px 14px; background: var(--card2); border-radius: 10px; margin-bottom: 6px; border-left: 3px solid var(--border); }
.account-row.active { border-left-color: var(--success); }
.account-user { font-weight: 700; font-size: 12px; }
.account-bal { color: var(--accent); font-weight: 700; font-size: 12px; margin-left: auto; margin-right: 15px; }
.account-bet { color: var(--warning); font-weight: 700; font-size: 12px; }
.total-box { display: flex; justify-content: space-between; padding: 14px; background: var(--card2); border-radius: 10px; margin-top: 12px; }
.total-item { text-align: center; }
.total-label { font-size: 9px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 1px; font-weight: 700; }
.total-value { font-size: 18px; font-weight: 800; color: var(--accent); margin-top: 4px; }
.history-grid { display: flex; flex-wrap: wrap; gap: 4px; padding: 10px; background: var(--card2); border-radius: 10px; min-height: 44px; }
.history-dot { width: 22px; height: 22px; border-radius: 50%; border: 1px solid var(--border); }
.history-dot.red { background: var(--red); border-color: var(--red); }
.history-dot.blue { background: var(--blue); border-color: var(--blue); }
.log-container { background: #05070d; border-radius: 10px; padding: 12px; height: 320px; overflow-y: auto; font-family: 'Consolas', monospace; font-size: 11px; line-height: 1.7; border: 1px solid var(--border); }
.log-line { display: flex; gap: 8px; }
.log-time { color: var(--text-muted); flex-shrink: 0; }
.log-line.green .log-msg { color: var(--success); }
.log-line.red .log-msg { color: var(--danger); }
.log-line.blue .log-msg { color: var(--info); }
.log-line.yellow .log-msg { color: var(--warning); }
.log-line.accent .log-msg { color: var(--accent); font-weight: 700; }
.log-line.purple .log-msg { color: var(--purple); font-weight: 700; }
.log-line.normal .log-msg { color: var(--text-dim); }
.toast-container { position: fixed; top: 80px; right: 20px; z-index: 1000; display: flex; flex-direction: column; gap: 10px; }
.toast { background: var(--card); border: 1px solid var(--border); border-left: 4px solid var(--accent); padding: 14px 20px; border-radius: 10px; font-size: 13px; font-weight: 600; min-width: 260px; }
.toast.success { border-left-color: var(--success); color: var(--success); }
.toast.error { border-left-color: var(--danger); color: var(--danger); }
.toast.warning { border-left-color: var(--warning); color: var(--warning); }
.mode-badge { display: inline-block; padding: 4px 10px; border-radius: 20px; font-size: 10px; font-weight: 800; letter-spacing: 1px; text-transform: uppercase; }
.mode-active { background: rgba(0,255,157,0.15); color: var(--success); }
.mode-warn { background: rgba(255,181,71,0.15); color: var(--warning); }
.mode-idle { background: rgba(139,152,169,0.15); color: var(--text-dim); }
.mode-alt { background: rgba(94,179,255,0.15); color: var(--info); }
.mode-opp { background: rgba(168,85,247,0.15); color: var(--purple); }
.checkbox-wrap { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; cursor: pointer; }
.checkbox-wrap input { width: 18px; height: 18px; accent-color: var(--accent); cursor: pointer; }
.checkbox-wrap label { font-size: 12px; color: var(--text-dim); cursor: pointer; font-weight: 600; }
.ruptura-box { background: linear-gradient(135deg, rgba(255,181,71,0.08), rgba(168,85,247,0.08)); border: 1px solid rgba(255,181,71,0.4); border-radius: 12px; padding: 14px; margin-bottom: 10px; }
.ruptura-titulo { font-size: 14px; font-weight: 800; color: var(--warning); margin-bottom: 10px; }
.ruptura-linea { font-size: 12px; color: var(--text-dim); margin-bottom: 4px; display: flex; justify-content: space-between; }
.ruptura-linea .pct { color: var(--accent); font-weight: 700; }
.pronostico-box { background: linear-gradient(135deg, rgba(0,229,255,0.1), rgba(168,85,247,0.1)); border: 2px solid var(--accent); border-radius: 12px; padding: 16px; margin: 10px 0; text-align: center; }
.pronostico-label { font-size: 10px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 2px; font-weight: 700; margin-bottom: 6px; }
.pronostico-valor { font-size: 42px; font-weight: 900; line-height: 1; }
.pronostico-valor.red { color: var(--red); }
.pronostico-valor.blue { color: var(--blue); }
.pronostico-valor.wait { color: var(--warning); }
.pronostico-conf { font-size: 14px; color: var(--accent); font-weight: 700; margin-top: 8px; }
.patron-grupo { background: var(--card2); border-radius: 10px; padding: 12px; border-left: 3px solid var(--info); margin-bottom: 8px; }
.patron-grupo.fuerte { border-left-color: var(--success); }
.patron-grupo.medio { border-left-color: var(--warning); }
.patron-grupo.debil { border-left-color: var(--text-muted); }
.patron-grupo-nombre { font-size: 12px; font-weight: 800; color: var(--accent); margin-bottom: 6px; }
.patron-grupo-linea { display: flex; justify-content: space-between; font-size: 11px; color: var(--text-dim); margin-bottom: 3px; }
::-webkit-scrollbar { width: 8px; }
::-webkit-scrollbar-track { background: var(--card2); }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 10px; }
</style>
</head>
<body>

<div id="activationScreen">
    <div class="activation-box">
        <div class="activation-logo">
            <div class="activation-logo-icon">⚡</div>
            <div class="activation-title">PREDICTOR PRO</div>
            <div class="activation-sub">Sistema de Activación</div>
        </div>
        <div class="activation-card">
            <div class="activation-card-title">🔑 ID de tu dispositivo</div>
            <div class="hwid-box" id="hwidBox" onclick="copyHwid()">Cargando...</div>
            <div class="hwid-hint">👆 Click para copiar</div>
        </div>
        <div class="activation-card">
            <div class="activation-card-title" style="color: var(--success);">🎁 Prueba gratuita 24H</div>
            <button class="btn btn-success btn-block btn-lg" id="btnTrial" onclick="activateTrial()">🎯 ACTIVAR PRUEBA GRATUITA</button>
        </div>
        <div class="activation-card">
            <div class="activation-card-title" style="color: var(--info);">📁 Cargar licencia</div>
            <input type="file" id="licFile" class="file-input-hidden" accept=".lic,.json,.txt" onchange="uploadLicense(event)">
            <label for="licFile" class="file-label">🔍 BUSCAR ARCHIVO .LIC</label>
            <div class="file-name" id="fileName"></div>
        </div>
        <div class="activation-card">
            <div class="activation-card-title" style="color: var(--warning);">📊 Estado</div>
            <div class="activation-status">
                <div class="activation-status-text warning" id="statusText">VERIFICANDO...</div>
                <div class="activation-status-info" id="statusInfo">Comprobando licencia...</div>
            </div>
            <button class="btn btn-primary btn-block" style="margin-top: 12px;" onclick="checkLicense()">✓ VERIFICAR DE NUEVO</button>
        </div>
    </div>
</div>

<div id="dashboardScreen">
    <div class="header">
        <div class="logo">
            <div class="logo-icon">⚡</div>
            <div>
                <div class="logo-text">PREDICTOR PRO</div>
                <div class="logo-sub">Análisis de Rupturas + IA</div>
            </div>
        </div>
        <div class="header-right">
            <div class="license-badge" id="licenseBadge">🔐</div>
            <div class="status-badge offline" id="statusBadge">
                <div class="status-dot"></div>
                <span id="headerStatusText">OFFLINE</span>
            </div>
        </div>
    </div>

    <div class="container">
        <div class="column">
            <div class="card">
                <div class="card-title">
                    <span>🎮 Control de sesión</span>
                    <span class="mode-badge mode-idle" id="modeBadge">ESPERANDO</span>
                </div>
                <div class="stats-grid">
                    <div class="stat"><div class="stat-label">Wins</div><div class="stat-value success" id="wins">0</div></div>
                    <div class="stat"><div class="stat-label">Losses</div><div class="stat-value danger" id="losses">0</div></div>
                    <div class="stat"><div class="stat-label">Winrate</div><div class="stat-value warning" id="winrate">0%</div></div>
                    <div class="stat"><div class="stat-label">Racha</div><div class="stat-value accent" id="racha">0</div></div>
                </div>
                <div class="btn-row" style="margin-top: 12px;">
                    <button class="btn btn-success btn-lg" id="btnStart" onclick="startSession()">▶️ INICIAR</button>
                    <button class="btn btn-danger btn-lg" id="btnStop" onclick="stopSession()" disabled>⏹ DETENER</button>
                </div>
            </div>

            <div class="card">
                <div class="card-title">
                    <span>👤 Cuentas</span>
                    <span id="accCount">0/3</span>
                </div>
                <div class="input-row">
                    <input class="input" id="accUser" placeholder="Usuario">
                    <input class="input" id="accPass" type="password" placeholder="Contraseña">
                </div>
                <div class="btn-row">
                    <button class="btn btn-primary" onclick="addAccount()">+ Agregar</button>
                    <button class="btn btn-primary" onclick="loginAll()">🔓 Login</button>
                </div>
                <div id="accountsList" style="margin-top: 14px;"></div>
                <div class="total-box">
                    <div class="total-item"><div class="total-label">Saldo</div><div class="total-value" id="totalBalance">$0.00</div></div>
                </div>
            </div>

            <div class="card">
                <div class="card-title"><span>⚙️ Auto Betting</span></div>
                <div class="input-row">
                    <div><label class="input-label">Apuesta inicial</label><input class="input" id="cfgInitial" type="number" step="0.1" value="0.10"></div>
                    <div><label class="input-label">Máx pérdidas</label><input class="input" id="cfgMaxLoss" type="number" value="3"></div>
                </div>
                <div class="input-row">
                    <div><label class="input-label">Máx apuesta</label><input class="input" id="cfgMaxBet" type="number" step="0.1" value="5.0"></div>
                    <div></div>
                </div>
                <div class="checkbox-wrap"><input type="checkbox" id="cfgMartingale" onchange="toggleMartingale()"><label for="cfgMartingale">🔁 Martingale</label></div>
                <div class="checkbox-wrap"><input type="checkbox" id="cfgAggressive" onchange="toggleAggressive()"><label for="cfgAggressive">⚡ Agresivo</label></div>
                <div class="checkbox-wrap"><input type="checkbox" id="cfgIAConfirm" checked onchange="toggleIAConfirm()"><label for="cfgIAConfirm">🧠 Solo apostar si IA confirma</label></div>
                <div class="checkbox-wrap"><input type="checkbox" id="cfgWait2Losses" onchange="toggleWait2Losses()"><label for="cfgWait2Losses">🎣 Apostar solo después de 2 losses</label></div>
                <div class="btn-row">
                    <button class="btn btn-ghost" onclick="saveSettings()">💾 Guardar</button>
                    <button class="btn btn-success" id="btnAutoBet" onclick="toggleAutoBet()" disabled>🎰 Auto Bet</button>
                </div>
                <div style="margin-top: 8px; text-align: center;"><span id="autoBetHint" style="font-size: 10px; color: var(--text-muted);">Inicia sesión y loguea cuentas</span></div>
            </div>
        </div>

        <div class="column">
            <div class="card">
                <div class="card-title">
                    <span>🎯 Predicción Matemática</span>
                    <span id="confidenceText" style="color: var(--info);">CONF 0%</span>
                </div>
                <div class="prediction-display">
                    <div class="pred-box"><div class="pred-box-label">Último</div><div class="pred-box-value" id="lastColor">—</div></div>
                    <div class="pred-box"><div class="pred-box-label">Predicción</div><div class="pred-box-value" id="predColor">—</div></div>
                    <div class="pred-box"><div class="pred-box-label">Últimos 6</div><div class="last6-grid" id="last6"></div></div>
                </div>
                <div class="confidence-bar"><div class="confidence-fill" id="confidenceFill" style="width: 0%;"></div></div>
                <div class="logic-box" id="logicBox">Esperando datos...</div>
            </div>

            <div class="card patron-card">
                <div class="card-title">
                    <span>🔍 Análisis de Rupturas</span>
                    <span id="patronBadge" style="font-size: 10px; color: var(--text-muted);">esperando</span>
                </div>
                <div id="patronContenido">
                    <div style="font-size: 12px; color: var(--text-dim); padding: 12px; text-align: center;">Esperando detección de patrón...</div>
                </div>
            </div>

            <div class="card ai-card">
                <div class="card-title">
                    <span>🧠 Análisis de IA (Gemini)</span>
                    <span id="aiStatus" style="font-size: 10px; color: var(--text-muted);">esperando...</span>
                </div>
                <div class="prediction-display" style="grid-template-columns: 1fr 1fr;">
                    <div class="pred-box"><div class="pred-box-label">IA sugiere</div><div class="pred-box-value" id="aiPred">—</div></div>
                    <div class="pred-box"><div class="pred-box-label">Confianza IA</div><div class="pred-box-value purple" id="aiConf">0%</div></div>
                </div>
                <div class="confidence-bar"><div class="confidence-fill purple" id="aiConfFill" style="width: 0%;"></div></div>
                <div class="logic-box purple" id="aiReason">Esperando análisis...</div>
                <div style="margin-top: 10px; text-align: center;"><span class="ai-coincide-badge wait" id="aiCoincideBadge">comparando...</span></div>
            </div>

            <div class="card stats-card">
                <div class="card-title">
                    <span>📊 Análisis histórico de rupturas</span>
                    <span id="totalDatos" style="font-size: 10px; color: var(--text-muted);">0 datos</span>
                </div>
                <div id="patronesList" style="display: flex; flex-direction: column; gap: 8px;"></div>
            </div>

            <div class="card">
                <div class="card-title"><span>📜 Historial</span></div>
                <div class="history-grid" id="historyGrid"></div>
            </div>

            <div class="card">
                <div class="card-title">
                    <span>📋 Log en vivo</span>
                    <button class="btn btn-ghost" style="padding: 6px 12px; font-size: 11px;" onclick="clearLog()">🗑</button>
                </div>
                <div class="log-container" id="logContainer"></div>
            </div>
        </div>
    </div>
</div>

<div class="toast-container" id="toastContainer"></div>

<script>
async function api(url, method='GET', data=null) {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (data) opts.body = JSON.stringify(data);
    const r = await fetch(url, opts);
    return await r.json();
}
function toast(msg, type='success') {
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = msg;
    document.getElementById('toastContainer').appendChild(el);
    setTimeout(() => el.remove(), 4000);
}
let currentHwid = '';
async function loadHwid() {
    const data = await api('/api/status');
    currentHwid = data.license.hwid;
    document.getElementById('hwidBox').textContent = currentHwid;
}
function copyHwid() {
    if (navigator.clipboard) navigator.clipboard.writeText(currentHwid).then(() => toast('Copiado', 'success'));
}
function setActivationStatus(text, info, type) {
    const el = document.getElementById('statusText');
    el.textContent = text; el.className = 'activation-status-text ' + type;
    document.getElementById('statusInfo').textContent = info;
}
async function activateTrial() {
    const btn = document.getElementById('btnTrial');
    btn.disabled = true; btn.textContent = 'ACTIVANDO...';
    const r = await api('/api/license/activate-trial', 'POST');
    if (r.success) { toast(r.message, 'success'); setActivationStatus('✅ ACTIVADO', r.message, 'success'); setTimeout(goToDashboard, 1200); }
    else { toast(r.message, 'error'); setActivationStatus('❌ NO', r.message, 'danger'); btn.disabled = false; btn.textContent = '🎯 ACTIVAR PRUEBA'; }
}
async function uploadLicense(event) {
    const file = event.target.files[0]; if (!file) return;
    document.getElementById('fileName').textContent = '📄 ' + file.name;
    const reader = new FileReader();
    reader.onload = async (e) => {
        const r = await api('/api/license/upload', 'POST', { contenido: e.target.result });
        if (r.success) { toast('OK', 'success'); setActivationStatus('✅ ACTIVADO', r.message, 'success'); setTimeout(goToDashboard, 1200); }
        else { toast(r.message, 'error'); setActivationStatus('❌ INVÁLIDO', r.message, 'danger'); }
    };
    reader.readAsText(file);
}
async function checkLicense() {
    const r = await api('/api/license/check', 'POST');
    if (r.success) { toast(r.message, 'success'); setActivationStatus('✅ OK', r.message, 'success'); setTimeout(goToDashboard, 1200); }
    else { toast(r.message, 'error'); setActivationStatus('🔒 NO', r.message, 'warning'); }
}
async function autoCheckOnLoad() {
    const data = await api('/api/status');
    if (data.license.valid) { setActivationStatus('✅ ACTIVADO', data.license.info, 'success'); setTimeout(goToDashboard, 800); }
    else setActivationStatus('🔒 DESACTIVADO', data.license.info || 'No activado', 'warning');
}
function goToDashboard() {
    document.getElementById('activationScreen').style.display = 'none';
    document.getElementById('dashboardScreen').style.display = 'block';
    updateStatus();
}
async function startSession() {
    const r = await api('/api/session/start', 'POST');
    if (r.success) { toast('Iniciado', 'success'); document.getElementById('btnStart').disabled = true; document.getElementById('btnStop').disabled = false; }
    else toast(r.message, 'error');
}
async function stopSession() {
    await api('/api/session/stop', 'POST');
    toast('Detenido', 'warning');
    document.getElementById('btnStart').disabled = false;
    document.getElementById('btnStop').disabled = true;
}
async function addAccount() {
    const u = document.getElementById('accUser').value.trim();
    const p = document.getElementById('accPass').value.trim();
    if (!u || !p) { toast('Faltan datos', 'error'); return; }
    const r = await api('/api/accounts/add', 'POST', { username: u, password: p });
    toast(r.message, r.success ? 'success' : 'error');
    if (r.success) { document.getElementById('accUser').value = ''; document.getElementById('accPass').value = ''; updateStatus(); }
}
async function removeAccount(id) {
    const r = await api('/api/accounts/remove', 'POST', { id });
    if (r.success) { toast(r.message, 'warning'); updateStatus(); }
}
async function loginAll() {
    toast('Login...', 'warning');
    await api('/api/accounts/login', 'POST');
    setTimeout(updateStatus, 2500); setTimeout(updateStatus, 5000);
}
function toggleMartingale() { if (document.getElementById('cfgMartingale').checked) document.getElementById('cfgAggressive').checked = false; }
function toggleAggressive() { if (document.getElementById('cfgAggressive').checked) document.getElementById('cfgMartingale').checked = false; }
async function toggleIAConfirm() {
    const enabled = document.getElementById('cfgIAConfirm').checked;
    await api('/api/betting/ia-confirm', 'POST', { enabled });
    toast(enabled ? '🧠 Solo con IA' : '⚡ Libre', 'success');
}
async function toggleWait2Losses() {
    const enabled = document.getElementById('cfgWait2Losses').checked;
    await api('/api/betting/wait-2-losses', 'POST', { enabled });
    toast(enabled ? '🎣 Esperar 2 losses' : '⚡ Normal', 'success');
}
async function saveSettings() {
    await api('/api/betting/settings', 'POST', {
        initial_bet: parseFloat(document.getElementById('cfgInitial').value),
        max_consecutive_losses: parseInt(document.getElementById('cfgMaxLoss').value),
        max_bet: parseFloat(document.getElementById('cfgMaxBet').value),
        martingale: document.getElementById('cfgMartingale').checked,
        aggressive: document.getElementById('cfgAggressive').checked
    });
    toast('Guardado', 'success');
}
async function toggleAutoBet() {
    const btn = document.getElementById('btnAutoBet');
    const isActive = btn.textContent.includes('Detener');
    btn.disabled = true;
    const r = await api(isActive ? '/api/betting/stop' : '/api/betting/start', 'POST');
    if (r.success) {
        btn.textContent = isActive ? '🎰 Auto Bet' : '⏹ Detener';
        btn.className = isActive ? 'btn btn-success' : 'btn btn-danger';
        toast(isActive ? 'Detenido' : 'Iniciado', isActive ? 'warning' : 'success');
    } else toast('❌ ' + (r.message||''), 'error');
    setTimeout(updateStatus, 500);
}
function clearLog() {
    document.getElementById('logContainer').innerHTML = '';
    document.getElementById('logContainer').dataset.firma = '';
}

let ultimoLogId = 0;
function renderLogs(logs) {
    const logCont = document.getElementById('logContainer');
    if (!logs || logs.length === 0) return;
    const ultimo = logs[logs.length - 1];
    if (!ultimo || ultimo.id === ultimoLogId) return;
    const primero = logs[0];
    const primerIdActual = logCont.firstElementChild ? parseInt(logCont.firstElementChild.dataset.id || '0') : 0;
    if (primero.id !== primerIdActual) {
        logCont.innerHTML = '';
        logs.forEach(l => {
            const div = document.createElement('div');
            div.className = 'log-line ' + (l.color || 'normal');
            div.dataset.id = l.id;
            div.innerHTML = `<span class="log-time">[${l.time}]</span><span class="log-msg">${l.msg}</span>`;
            logCont.appendChild(div);
        });
    } else {
        let lastRendered = ultimoLogId;
        logs.forEach(l => {
            if (l.id > lastRendered) {
                const div = document.createElement('div');
                div.className = 'log-line ' + (l.color || 'normal');
                div.dataset.id = l.id;
                div.innerHTML = `<span class="log-time">[${l.time}]</span><span class="log-msg">${l.msg}</span>`;
                logCont.appendChild(div);
            }
        });
        while (logCont.children.length > 200) logCont.removeChild(logCont.firstChild);
    }
    ultimoLogId = ultimo.id;
    logCont.scrollTop = logCont.scrollHeight;
}

async function updateStatus() {
    try {
        const data = await api('/api/status');
        document.getElementById('licenseBadge').textContent = '🔐 ' + data.license.info;
        document.getElementById('wins').textContent = data.session.wins;
        document.getElementById('losses').textContent = data.session.losses;
        const t = data.session.wins + data.session.losses;
        document.getElementById('winrate').textContent = t > 0 ? Math.round(data.session.wins/t*100) + '%' : '0%';
        document.getElementById('racha').textContent = data.predictor.consecutive_losses;

        const badge = document.getElementById('statusBadge');
        if (data.session.running) {
            badge.className = 'status-badge online';
            document.getElementById('headerStatusText').textContent = 'ONLINE';
            document.getElementById('btnStart').disabled = true;
            document.getElementById('btnStop').disabled = false;
        } else {
            badge.className = 'status-badge offline';
            document.getElementById('headerStatusText').textContent = 'OFFLINE';
            document.getElementById('btnStart').disabled = false;
            document.getElementById('btnStop').disabled = true;
        }

        const modeBadge = document.getElementById('modeBadge');
        const mode = data.predictor.mode_info;
        modeBadge.textContent = mode;
        if (mode.includes('OPUESTO')) modeBadge.className = 'mode-badge mode-opp';
        else if (mode.includes('ALTERNANCIA')) modeBadge.className = 'mode-badge mode-alt';
        else if (mode.includes('perdidas') || mode.includes('pérdidas')) modeBadge.className = 'mode-badge mode-warn';
        else if (data.session.running) modeBadge.className = 'mode-badge mode-active';
        else modeBadge.className = 'mode-badge mode-idle';

        const hist = data.predictor.history;
        const last = hist.length > 0 ? hist[hist.length - 1] : null;
        const lastEl = document.getElementById('lastColor');
        if (last) { lastEl.textContent = last.toUpperCase(); lastEl.className = 'pred-box-value ' + last; }
        else lastEl.className = 'pred-box-value';

        const predEl = document.getElementById('predColor');
        const pred = data.predictor.last_prediction;
        if (pred) { predEl.textContent = pred.toUpperCase(); predEl.className = 'pred-box-value ' + pred; }
        else { predEl.textContent = '—'; predEl.className = 'pred-box-value'; }

        const last6 = document.getElementById('last6');
        last6.innerHTML = '';
        (data.predictor.last_colors || []).forEach(c => {
            const d = document.createElement('div');
            d.className = 'last6-dot ' + c;
            last6.appendChild(d);
        });

        let conf = 0;
        if (pred) {
            if (hist.length >= 3) {
                const l3 = hist.slice(-3);
                if (l3[0] === l3[1] && l3[1] === l3[2]) conf = 92;
                else if (hist[hist.length-1] === hist[hist.length-2]) conf = 85;
                else conf = 75;
            } else conf = 75;
        }
        document.getElementById('confidenceText').textContent = `CONF ${conf}%`;
        document.getElementById('confidenceFill').style.width = conf + '%';

        let logic = 'Esperando datos...';
        if (pred) {
            if (data.predictor.esperando_opuesto) logic = `🔀 OPUESTO tras ruptura larga → ${pred.toUpperCase()}`;
            else if (data.predictor.modo_alternancia) logic = `🔁 ALTERNANCIA (${data.predictor.alternancia_len}) → ${pred.toUpperCase()}`;
            else logic = `📈 TENDENCIA → seguir ${pred.toUpperCase()} (${conf}%)`;
        }
        document.getElementById('logicBox').textContent = logic;

        const pron = data.pronostico_actual;
        const cont = document.getElementById('patronContenido');
        if (pron) {
            let html = '';
            const det = pron.detalles || {};
            const pat = det.patron_actual;
            const rup = det.ruptura;
            const sim = det.similar;

            if (pat) {
                if (pat.tipo === 'GUSANO') {
                    html += `<div class="ruptura-box"><div class="ruptura-titulo">🐛 GUSANO ${pat.subtipo.toUpperCase()} de ${pat.tamano} ${pat.color_dominante.toUpperCase()}</div></div>`;
                } else if (pat.tipo === 'ALTERNANCIA') {
                    html += `<div class="ruptura-box"><div class="ruptura-titulo">🔁 ALTERNANCIA ${pat.subtipo.toUpperCase()} (${pat.tamano} cambios)</div></div>`;
                }
            }

            if (rup && sim) {
                html += `<div class="ruptura-box">
                    <div class="ruptura-titulo">⚠️ RUPTURA DE ${rup.tipo_roto} ${rup.subtipo_roto.toUpperCase()}</div>
                    <div style="font-size: 11px; color: var(--text-dim); margin-bottom: 8px;">Casos históricos similares: <strong style="color: var(--accent);">${sim.casos}</strong></div>
                    <div class="ruptura-linea"><span>🟢 Nueva racha ruptor</span><span class="pct">${sim.categorias.nueva_racha_ruptor}</span></div>
                    <div class="ruptura-linea"><span>🔄 Rebote al original</span><span class="pct">${sim.categorias.rebote_original}</span></div>
                    <div class="ruptura-linea"><span>🔁 Alternancia post</span><span class="pct">${sim.categorias.alternancia_post}</span></div>
                    <div class="ruptura-linea"><span>🟡 Mixto</span><span class="pct">${sim.categorias.mixto}</span></div>
                    <div style="margin-top: 10px; padding-top: 10px; border-top: 1px solid var(--border);">
                        <div class="ruptura-linea"><span>Próxima tirada → ${sim.proxima_pred.toUpperCase()}</span><span class="pct">${sim.proxima_conf}%</span></div>
                    </div>
                </div>`;
            }

            if (pron.pred) {
                const cls = pron.pred === 'red' ? 'red' : 'blue';
                html += `<div class="pronostico-box">
                    <div class="pronostico-label">🎯 Pronóstico estadístico</div>
                    <div class="pronostico-valor ${cls}">${pron.pred.toUpperCase()}</div>
                    <div class="pronostico-conf">${pron.conf}% de confianza</div>
                    <div style="font-size: 11px; color: var(--text-dim); margin-top: 8px;">${pron.razon}</div>
                </div>`;
            } else {
                html += `<div class="ruptura-box"><div style="font-size: 12px; color: var(--text-muted);">⏸ ${pron.razon || 'Sin pronóstico claro'}</div></div>`;
            }

            cont.innerHTML = html;
            document.getElementById('patronBadge').textContent = rup ? '⚠️ RUPTURA' : (pat ? 'patrón' : 'esperando');
        } else {
            cont.innerHTML = '<div style="font-size: 12px; color: var(--text-dim); padding: 12px; text-align: center;">Esperando detección de patrón...</div>';
        }

        const ai = data.ai;
        if (ai && ai.prediccion) {
            const aiPredEl = document.getElementById('aiPred');
            let t = '—', cls = 'pred-box-value';
            if (ai.prediccion === 'R') { t = 'R'; cls = 'pred-box-value red'; }
            else if (ai.prediccion === 'B') { t = 'B'; cls = 'pred-box-value blue'; }
            else { t = '⏸'; cls = 'pred-box-value wait'; }
            aiPredEl.textContent = t; aiPredEl.className = cls;
            document.getElementById('aiConf').textContent = (ai.confianza || 0) + '%';
            document.getElementById('aiConfFill').style.width = (ai.confianza || 0) + '%';
            document.getElementById('aiReason').textContent = ai.razonamiento || '—';
            const statusEl = document.getElementById('aiStatus');
            if (data.session.esperando_ia) statusEl.textContent = '⏳ esperando...';
            else if (ai.recomendacion === 'APOSTAR') statusEl.textContent = '✓ apostar';
            else statusEl.textContent = '⏸ esperar';
            const coincideBadge = document.getElementById('aiCoincideBadge');
            if (pred) {
                const ps = pred === 'red' ? 'R' : 'B';
                if (ai.prediccion === ps) { coincideBadge.textContent = '✓ CONFIRMA'; coincideBadge.className = 'ai-coincide-badge match'; }
                else if (ai.prediccion === 'ESPERAR') { coincideBadge.textContent = '⏸ ESPERAR'; coincideBadge.className = 'ai-coincide-badge wait'; }
                else { coincideBadge.textContent = '⚠️ DISCREPA'; coincideBadge.className = 'ai-coincide-badge diff'; }
            }
        }

        const analisis = data.analisis;
        if (analisis) {
            document.getElementById('totalDatos').textContent = analisis.total_global + ' datos';
            const lista = document.getElementById('patronesList');
            lista.innerHTML = '';
            (analisis.grupos || []).forEach(g => {
                let clase = 'patron-grupo';
                if (g.categorias) {
                    const maxPct = Math.max(g.sig_pct.red, g.sig_pct.blue);
                    if (maxPct >= 65) clase += ' fuerte';
                    else if (maxPct >= 58) clase += ' medio';
                    else clase += ' debil';
                } else clase += ' debil';
                let html = `<div class="patron-grupo-nombre">${g.nombre}</div>`;
                if (g.categorias) {
                    const c = g.categorias;
                    const t = c.nueva_racha_ruptor + c.rebote_original + c.alternancia_post + c.mixto;
                    const p = (n) => t > 0 ? Math.round(n/t*100) : 0;
                    html += `<div class="patron-grupo-linea"><span>🟢 Nueva racha</span><span>${p(c.nueva_racha_ruptor)}%</span></div>`;
                    html += `<div class="patron-grupo-linea"><span>🔄 Rebote</span><span>${p(c.rebote_original)}%</span></div>`;
                    html += `<div class="patron-grupo-linea"><span>🔁 Alternancia</span><span>${p(c.alternancia_post)}%</span></div>`;
                    html += `<div class="patron-grupo-linea"><span>🟡 Mixto</span><span>${p(c.mixto)}%</span></div>`;
                    html += `<div style="margin-top: 6px; padding-top: 6px; border-top: 1px solid var(--border); font-size: 11px;">`;
                    html += `<span style="color: var(--accent);">Próxima: ${g.proxima_pred.toUpperCase()} (${g.proxima_conf}%)</span>`;
                    html += `<span style="color: var(--text-muted); margin-left: 8px;">${g.casos} casos</span></div>`;
                } else if (g.descripcion) {
                    html += `<div class="patron-grupo-linea"><span>${g.descripcion}</span></div>`;
                }
                const item = document.createElement('div');
                item.className = clase;
                item.innerHTML = html;
                lista.appendChild(item);
            });
        }

        const accList = document.getElementById('accountsList');
        accList.innerHTML = '';
        data.betting.accounts.forEach(a => {
            const row = document.createElement('div');
            row.className = 'account-row' + (a.is_logged_in ? ' active' : '');
            row.innerHTML = `
                <span>${a.is_logged_in ? '🟢' : '🔴'}</span>
                <span class="account-user">${a.username}</span>
                <span class="account-bal">$${a.balance.toFixed(2)}</span>
                <span class="account-bet">$${a.current_bet.toFixed(2)}</span>
                <button class="btn btn-ghost" style="padding: 4px 8px; font-size: 10px; margin-left: 8px;" onclick="removeAccount(${a.id})">✕</button>
            `;
            accList.appendChild(row);
        });
        document.getElementById('accCount').textContent = `${data.betting.accounts.length}/3`;
        document.getElementById('totalBalance').textContent = '$' + data.betting.total_balance.toFixed(2);

        const hg = document.getElementById('historyGrid');
        hg.innerHTML = '';
        hist.slice(-30).forEach(c => {
            const d = document.createElement('div');
            d.className = 'history-dot ' + c;
            hg.appendChild(d);
        });

        renderLogs(data.logs);

        const ab = document.getElementById('btnAutoBet');
        const activas = data.betting.accounts.filter(a => a.is_logged_in).length;
        const listo = data.session.running && activas > 0;
        if (data.session.betting_active) { ab.textContent = '⏹ Detener'; ab.className = 'btn btn-danger'; }
        else { ab.textContent = '🎰 Auto Bet'; ab.className = 'btn btn-success'; }
        ab.disabled = !listo;
        const hint = document.getElementById('autoBetHint');
        if (!data.session.running && activas === 0) hint.textContent = '⚠️ Inicia sesión + loguea';
        else if (!data.session.running) hint.textContent = '⚠️ Falta iniciar sesión';
        else if (activas === 0) hint.textContent = '⚠️ Falta loguear cuentas';
        else if (data.session.betting_active) {
            if (data.session.esperar_2_losses && !data.session.habilitado_apostar) {
                hint.textContent = `🎣 Esperando 2 losses (${data.session.losses_seguidas}/2)`;
            } else hint.textContent = '✅ ACTIVO';
        }
        else hint.textContent = '✅ Listo';

        if (data.session.ia_confirm_required !== undefined) {
            document.getElementById('cfgIAConfirm').checked = data.session.ia_confirm_required;
        }
        if (data.session.esperar_2_losses !== undefined) {
            document.getElementById('cfgWait2Losses').checked = data.session.esperar_2_losses;
        }
    } catch (e) { console.error(e); }
}

(async () => { await loadHwid(); await autoCheckOnLoad(); })();
setInterval(() => { if (document.getElementById('dashboardScreen').style.display === 'block') updateStatus(); }, 1500);
</script>
</body>
</html>
"""


# ============================================================
# ============ RUTAS ============
# ============================================================

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route('/api/status')
def status():
    ai_data = analyst.get_analysis()
    analisis = historial.get_resumen(analizador)
    logs_enviar = state['logs'][-150:]
    return jsonify({
        'license': {'valid': license_mgr.is_valid(), 'info': license_mgr.get_info(), 'hwid': license_mgr.get_hwid()},
        'session': {
            'running': state['running'], 'betting_active': state['betting_active'],
            'wins': state['wins'], 'losses': state['losses'],
            'esperando_ia': state['esperando_ia'],
            'ia_confirm_required': state['ia_confirm_required'],
            'esperar_2_losses': state['esperar_2_losses'],
            'losses_seguidas': state['losses_seguidas'],
            'habilitado_apostar': state['habilitado_apostar']
        },
        'predictor': predictor.get_state(),
        'betting': betting.get_state(),
        'ai': ai_data,
        'analisis': analisis,
        'pronostico_actual': state['pronostico_actual'],
        'logs': logs_enviar,
        'logs_total': state['_log_counter']
    })


@app.route('/api/license/activate-trial', methods=['POST'])
def activate_trial():
    ok, msg = license_mgr.activar_trial()
    return jsonify({'success': ok, 'message': msg})


@app.route('/api/license/check', methods=['POST'])
def check_license():
    ok, msg = license_mgr.check_activation()
    return jsonify({'success': ok, 'message': msg})


@app.route('/api/license/upload', methods=['POST'])
def upload_license():
    data = request.json
    contenido = data.get('contenido', '')
    if not contenido: return jsonify({'success': False, 'message': 'Archivo vacío'})
    ok, msg = license_mgr.cargar_licencia(contenido)
    return jsonify({'success': ok, 'message': msg})


@app.route('/api/session/start', methods=['POST'])
def start_session():
    if state['running']: return jsonify({'success': False, 'message': 'Ya corriendo'})
    if not license_mgr.is_valid(): return jsonify({'success': False, 'message': 'Licencia inválida'})

    predictor.reset_session()
    state['running'] = True
    state['last_processed_index'] = 0
    state['prediction_index'] = 0
    state['wins'] = 0
    state['losses'] = 0
    state['logs'] = []
    state['_log_counter'] = 0
    state['esperando_ia'] = False
    state['pronostico_actual'] = None
    state['losses_seguidas'] = 0
    state['habilitado_apostar'] = not state['esperar_2_losses']
    state['ia_fallo'] = False

    log("Sesión iniciada", "green")
    log("Motor: Análisis de Rupturas", "blue")
    if state['esperar_2_losses']:
        log("🎣 Filtro activo: esperar 2 pérdidas seguidas", "yellow")
    total_datos = historial.get_resumen(analizador).get('total_global', 0)
    log(f"📊 Datos históricos: {total_datos}", "green")
    if analyst.enabled:
        if state['ia_confirm_required']: log("🧠 IA Gemini activa (apuesta solo si confirma)", "purple")
        else: log("🧠 IA Gemini activa (informativa)", "purple")

    threading.Thread(target=api_loop, daemon=True).start()
    return jsonify({'success': True})


@app.route('/api/session/stop', methods=['POST'])
def stop_session():
    state['running'] = False
    state['betting_active'] = False
    state['esperando_ia'] = False
    log("Sesión detenida", "yellow")
    return jsonify({'success': True})


@app.route('/api/betting/start', methods=['POST'])
def start_betting():
    activas = len(betting.get_active_accounts())
    if not state['running']:
        return jsonify({'success': False, 'message': 'Inicia sesión primero'})
    if activas == 0:
        return jsonify({'success': False, 'message': 'Login cuentas primero'})
    for a in betting.get_active_accounts():
        a.consecutive_losses = 0
        a.current_bet = betting.settings['initial_bet']
    state['betting_active'] = True
    log(f"🎰 Auto bet ACTIVADO ({activas} cuentas)", "green")
    return jsonify({'success': True})


@app.route('/api/betting/stop', methods=['POST'])
def stop_betting():
    state['betting_active'] = False
    state['esperando_ia'] = False
    log("Auto bet detenido", "yellow")
    return jsonify({'success': True})


@app.route('/api/betting/settings', methods=['POST'])
def update_settings():
    data = request.json
    betting.update_settings({
        'initial_bet': float(data.get('initial_bet', 0.1)),
        'max_consecutive_losses': int(data.get('max_consecutive_losses', 3)),
        'max_bet': float(data.get('max_bet', 5.0)),
        'martingale': bool(data.get('martingale', False)),
        'aggressive': bool(data.get('aggressive', False))
    })
    log("Config actualizada", "blue")
    return jsonify({'success': True})


@app.route('/api/betting/ia-confirm', methods=['POST'])
def set_ia_confirm():
    data = request.json
    state['ia_confirm_required'] = bool(data.get('enabled', True))
    state['esperando_ia'] = False
    log(f"🧠 Filtro IA: {'ACTIVADO' if state['ia_confirm_required'] else 'DESACTIVADO'}", "purple")
    return jsonify({'success': True, 'enabled': state['ia_confirm_required']})


@app.route('/api/betting/wait-2-losses', methods=['POST'])
def set_wait_2_losses():
    data = request.json
    state['esperar_2_losses'] = bool(data.get('enabled', False))
    if state['esperar_2_losses']:
        state['losses_seguidas'] = 0
        state['habilitado_apostar'] = False
        log("🎣 Filtro ACTIVADO: esperar 2 losses", "yellow")
    else:
        state['habilitado_apostar'] = True
        log("🎣 Filtro DESACTIVADO", "yellow")
    return jsonify({'success': True, 'enabled': state['esperar_2_losses']})


@app.route('/api/accounts/add', methods=['POST'])
def add_account():
    data = request.json
    ok, msg = betting.add_account(data.get('username', ''), data.get('password', ''))
    if ok: log(msg, "green")
    return jsonify({'success': ok, 'message': msg})


@app.route('/api/accounts/remove', methods=['POST'])
def remove_account():
    data = request.json
    ok, msg = betting.remove_account(int(data.get('id', 0)))
    if ok: log(msg, "yellow")
    return jsonify({'success': ok, 'message': msg})


@app.route('/api/accounts/login', methods=['POST'])
def login_accounts():
    def _do():
        log("🔓 Login de cuentas...", "blue")
        results = betting.login_all()
        for r in results:
            log(r, "green" if r.startswith("OK") else "red")
        active = len(betting.get_active_accounts())
        if active > 0: log(f"✅ {active} cuenta(s) lista(s)", "green")
        else: log("❌ 0 cuentas conectadas", "red")
    threading.Thread(target=_do, daemon=True).start()
    return jsonify({'success': True})


# ============================================================
# ============ LOOP API ============
# ============================================================

def api_loop():
    while state['running']:
        try:
            r = requests.post(API_URL, headers=API_HEADERS, timeout=5)
            if r.ok:
                data = r.json()
                if data.get('code') == 1:
                    new = data['data']['ori'][state['last_processed_index']:]
                    if new:
                        state['last_processed_index'] += len(new)
                        for c in new:
                            process_color(str(c).lower())
        except: pass
        time.sleep(2)


def process_color(color):
    if not state['running']: return
    if color not in ['red', 'blue']: return
    state['last_color_time'] = datetime.now()
    historial.registrar_color(color)
    predictor.process_color(color)
    log(f"Color: {color.upper()}", "blue")
    if predictor.last_prediction is not None: verify_prediction()
    else: process_round()


def process_round():
    if not predictor.session_history or predictor.last_prediction is not None:
        return
    colores = list(predictor.session_history)

    pronostico = analizador.generar_pronostico(colores)
    state['pronostico_actual'] = pronostico

    pred_final = pronostico['pred']
    conf_final = pronostico['conf']

    if not pred_final:
        pred_mate, conf_mate, logic = predictor.get_prediction()
        if not pred_mate:
            return
        pred_final = pred_mate
        conf_final = int(conf_mate * 100)
        logic_final = logic
    else:
        logic_final = f"{pronostico['razon']}"

    state['prediction_index'] += 1
    predictor.last_prediction = pred_final
    state['ultima_pred'] = pred_final
    state['ultimo_modo'] = predictor.get_mode_info()

    puede_apostar_ahora = state['habilitado_apostar']

    log(f"🎯 Pred #{state['prediction_index']}: {pred_final.upper()} ({conf_final}%) - {logic_final}", "accent")

    if state['ia_confirm_required'] and analyst.enabled:
        state['esperando_ia'] = True
        contexto = analizador.construir_contexto_ia(colores, pronostico)
        log(f"🧠 Enviando a IA...", "purple")
        threading.Thread(
            target=analizar_y_apostar_con_ia,
            args=(colores, pred_final, contexto, puede_apostar_ahora),
            daemon=True
        ).start()
    else:
        if state['betting_active']:
            if puede_apostar_ahora:
                log(f"📐 Modo libre → Apostando según mate: {pred_final.upper()}", "accent")
                place_auto_bet(pred_final)
            else:
                log(f"⏳ Esperando 2 losses ({state['losses_seguidas']}/2)", "normal")
        if analyst.enabled:
            contexto = analizador.construir_contexto_ia(colores, pronostico)
            threading.Thread(
                target=analizar_solo_informativo,
                args=(colores, pred_final, contexto),
                daemon=True
            ).start()


def analizar_y_apostar_con_ia(colores, pred_mate, contexto, puede_apostar):
    result = analyst.analizar(colores, contexto)
    state['esperando_ia'] = False

    if not result or not result.get('prediccion'):
        log("🧠 IA: no respondió", "yellow")
        log("⏸ Apuesta CANCELADA (IA no respondió)", "yellow")
        state['ia_fallo'] = True
        return

    state['ia_fallo'] = False
    pred_ia = result['prediccion']
    conf_ia = result.get('confianza', 0)
    razon = result.get('razonamiento', '')
    pred_short = 'R' if pred_mate == 'red' else 'B'
    state['ultima_ia'] = {'pred': pred_ia, 'conf': conf_ia, 'razon': razon}

    log(f"🧠 IA: {pred_ia} ({conf_ia}%) - \"{razon}\"", "purple")

    if pred_ia == pred_short:
        log(f"✅ IA CONFIRMA → Apostando {pred_mate.upper()}", "green")
        if state['betting_active'] and puede_apostar:
            place_auto_bet(pred_mate)
        elif not puede_apostar:
            log(f"⏳ Esperando 2 losses ({state['losses_seguidas']}/2)", "yellow")
    elif pred_ia == 'ESPERAR':
        log(f"⏸ IA recomienda ESPERAR → No apostar", "yellow")
    else:
        log(f"⚠️ IA DISCREPA (mate {pred_short} vs IA {pred_ia}) → Apostando según IA: {pred_ia}", "yellow")
        if state['betting_active'] and puede_apostar:
            side = 'red' if pred_ia == 'R' else 'blue'
            place_auto_bet(side)
        elif not puede_apostar:
            log(f"⏳ Esperando 2 losses", "yellow")


def analizar_solo_informativo(colores, pred_mate, contexto):
    result = analyst.analizar(colores, contexto)
    if not result or not result.get('prediccion'):
        return
    pred_ia = result['prediccion']
    conf_ia = result.get('confianza', 0)
    razon = result.get('razonamiento', '')
    state['ultima_ia'] = {'pred': pred_ia, 'conf': conf_ia, 'razon': razon}
    log(f"🧠 IA (info): {pred_ia} ({conf_ia}%) - \"{razon}\"", "purple")


def verify_prediction():
    actual = predictor.session_history[-1] if predictor.session_history else None
    if actual not in ['red', 'blue']: return

    modo_actual = predictor.get_mode_info()
    correct = predictor.update_prediction(actual)

    ia_data = state.get('ultima_ia') or {}
    historial.registrar_prediccion(
        pred_mate=state.get('ultima_pred'),
        modo=modo_actual,
        pred_ia=ia_data.get('pred'),
        conf_ia=ia_data.get('conf'),
        razon_ia=ia_data.get('razon'),
        resultado=actual
    )
    state['ultima_ia'] = None

    if not correct and state['betting_active'] and not predictor.modo_alternancia:
        ok, msg = betting.update_bets_after_loss()
        if not ok:
            log(f"Stop loss: {msg}", "red")
            state['betting_active'] = False

    if correct:
        state['wins'] += 1
        betting.update_balances()
        log(f"✅ #{state['prediction_index']} WIN", "green")
        if state['esperar_2_losses']:
            state['losses_seguidas'] = 0
            state['habilitado_apostar'] = False
            log("🎣 WIN → vuelve a esperar 2 losses", "yellow")
        if state['betting_active'] and not predictor.modo_alternancia:
            betting.reset_bets_after_win()
    else:
        state['losses'] += 1
        log(f"❌ #{state['prediction_index']} LOSS", "red")
        if state['esperar_2_losses']:
            state['losses_seguidas'] += 1
            if state['losses_seguidas'] >= 2 and not state['habilitado_apostar']:
                state['habilitado_apostar'] = True
                log("🎯 2 losses → APUESTAS HABILITADAS", "green")

    predictor.last_prediction = None
    process_round()


def place_auto_bet(pred):
    results, total = betting.place_bet_all(pred)
    for r in results:
        log(r, "green" if r.startswith("OK") else "red")
    if total > 0:
        log(f"💵 Total apostado: ${total:.2f}", "blue")


# ============================================================
# ============ MAIN ============
# ============================================================

def open_browser():
    time.sleep(4)
    url = 'http://localhost:5000'
    try:
        if webbrowser.open(url): return
    except: pass
    try:
        if platform.system() == "Windows":
            subprocess.Popen(['cmd', '/c', 'start', '', url], shell=False)
    except: pass
    print("=" * 60)
    print(f"  ⚠️  Abre MANUALMENTE: {url}")
    print("=" * 60)


if __name__ == '__main__':
    print("=" * 60)
    print("  PREDICTOR PRO v3.3 - Análisis de Rupturas (onefile)")
    print("=" * 60)
    print(f"  📁 BASE_DIR: {BASE_DIR}")
    if analyst.enabled: print(f"  🧠 IA: {GEMINI_MODEL}")
    print(f"  📊 Datos: {historial.get_resumen(analizador).get('total_global', 0)}")
    print(f"  🔬 Motor: Análisis de Rupturas unificado")
    print()
    print("  Abriendo: http://localhost:5000")
    print("=" * 60)
    threading.Thread(target=open_browser, daemon=True).start()
    try:
        app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
    except KeyboardInterrupt:
        print("\nServidor detenido.")