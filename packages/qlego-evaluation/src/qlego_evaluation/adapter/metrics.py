class MetricsAggregator:
    def __init__( self, qc ):
        self.metrics = []
        self.qc = qc
        self.res_dict = {}
    
    def append(self, metrics ):
        self.metrics += metrics

    def compute( self ):
        for metric in self.metrics:
            metric = metric( self.qc )
            self.res_dict[metric.name] = metric.compute()
        return self.res_dict
    

class BaseMetric:
    def __init__(self, qc ):
        self.qc = qc

    def compute(self):
        pass

class GateCount(BaseMetric):
    name = "Gate Count"
    def compute(self):
        return self.qc.size()
    
class Depth(BaseMetric):
    name = "Circuit Depth"
    def compute(self):
        return self.qc.depth()
    
class Q2Count(BaseMetric):
    name = "2Q Count"
    def compute(self):
        return sum(1 for inst, qargs, _ in self.qc.data if len(qargs) == 2)
    
class Q2Depth(BaseMetric):
    name = "2Q Depth"
    def compute(self):
        qc = self.qc
        t = [0] * qc.num_qubits
        depth = 0

        for inst, qargs, _ in qc.data:
            if len(qargs) != 2:
                continue
            qs = [qb._index for qb in qargs]  
            start = max(t[qs[0]], t[qs[1]]) + 1
            t[qs[0]] = t[qs[1]] = start
            depth = max(depth, start)

        return depth