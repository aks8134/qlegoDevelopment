import os
from qlego.qpass import QPass

class MQTWorkloadPass(QPass):
    name = "MQT Workload Pass"
    venv_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.venv/bin/python"))

    def run( self ):
        pass

