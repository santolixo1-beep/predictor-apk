# main.py - Lanzador de la app para Android
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.clock import Clock
import threading
import time
import sys
import os

# Asegurar que la app encuentre tu predictor.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

class PredictorApp(App):
    def build(self):
        # Una pantalla simple mientras carga
        self.layout = BoxLayout(orientation='vertical')
        self.label = Label(text="Iniciando Predictor...\nEspera un momento")
        self.layout.add_widget(self.label)
        return self.layout

    def on_start(self):
        # Iniciar el servidor Flask en un hilo separado
        def run_server():
            try:
                # Importar tu aplicación Flask desde predictor.py
                # NOTA: Aquí importamos la variable 'app' de tu predictor.py
                # Si tu variable se llama diferente, ajústalo aquí abajo.
                from predictor import app as flask_app
                
                # Ejecutar el servidor en un puerto local
                flask_app.run(host='127.0.0.1', port=5000, debug=False, use_reloader=False, threaded=True)
            except Exception as e:
                print(f"Error al iniciar el servidor: {e}")

        server_thread = threading.Thread(target=run_server, daemon=True)
        server_thread.start()

        # Esperar un poco a que el servidor levante y luego abrir el navegador
        # En Android, abrimos la URL en el navegador del sistema
        Clock.schedule_once(self.open_browser, 3)

    def open_browser(self, dt):
        try:
            from jnius import autoclass
            # Abrir la URL en el navegador web del teléfono
            Intent = autoclass('android.content.Intent')
            Uri = autoclass('android.net.Uri')
            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            
            intent = Intent(Intent.ACTION_VIEW)
            intent.setData(Uri.parse('http://127.0.0.1:5000'))
            
            current_activity = PythonActivity.mActivity
            current_activity.startActivity(intent)
        except Exception as e:
            print(f"Error al abrir el navegador: {e}")
            # Si falla, al menos actualizar el texto en la pantalla
            self.label.text = "Servidor corriendo.\nAbre el navegador en:\nhttp://127.0.0.1:5000"

if __name__ == '__main__':
    PredictorApp().run()