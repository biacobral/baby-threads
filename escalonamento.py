# -*- coding: utf-8 -*-
"""
Políticas de escalonamento da fila de atendimento do berçário.

Todas as filas guardam os pedidos numa lista e diferem só na chave usada
para decidir qual pedido sai primeiro:
  - fifo:     ordem de chegada
  - sjf:      menor tempo de atendimento primeiro (não preemptivo)
  - priority: prioridade da necessidade, com aging para evitar starvation
"""

import threading
import time

# prioridade 1 = mais urgente. A duração é sorteada dentro da faixa quando o
# pedido é criado, assim o SJF já sabe quanto tempo cada atendimento leva.
NECESSIDADES = {
    "fome":    {"prioridade": 1, "duracao": (1.0, 1.5)},
    "fralda":  {"prioridade": 2, "duracao": (0.8, 1.2)},
    "higiene": {"prioridade": 3, "duracao": (0.5, 0.8)},
    "sono":    {"prioridade": 4, "duracao": (0.3, 0.6)},
}

# a cada INTERVALO_AGING segundos esperando, o pedido sobe um nível de prioridade
INTERVALO_AGING = 1.0


class Fila:
    def __init__(self):
        self._itens = []
        self._cond = threading.Condition()

    def chave(self, pedido):
        return pedido["timestamp"]

    def put(self, pedido):
        with self._cond:
            self._itens.append(pedido)
            self._cond.notify()

    def get(self, timeout=None):
        with self._cond:
            if not self._cond.wait_for(lambda: self._itens, timeout):
                return None
            pedido = min(self._itens, key=self.chave)
            self._itens.remove(pedido)
            return pedido

    def snapshot(self):
        with self._cond:
            return sorted(self._itens, key=self.chave)

    def notify_all(self):
        with self._cond:
            self._cond.notify_all()

    def __len__(self):
        with self._cond:
            return len(self._itens)

    def __iter__(self):
        return iter(self.snapshot())


class FilaFIFO(Fila):
    pass


class FilaSJF(Fila):
    def chave(self, pedido):
        return (pedido["duracao"], pedido["timestamp"])


class FilaPrioridade(Fila):
    def chave(self, pedido):
        espera = time.time() - pedido["timestamp"]
        prioridade = pedido["prioridade"] - int(espera / INTERVALO_AGING)
        return (prioridade, pedido["timestamp"])


POLITICAS = {
    "fifo": FilaFIFO,
    "sjf": FilaSJF,
    "priority": FilaPrioridade,
}


def criar_fila(politica):
    return POLITICAS[politica]()
