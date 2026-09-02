import threading
import time
import random
import sys

fila = []#Lista compartilhada das Threads
atendimentos = []  # histórico de bebe_id, tipo, tempo_espera...
rodando = True#Flag para sinalizar se para ou não
TIPOS_NECESSIDADES = ["fome", "fralda", "sono", "higiene"]
lock_fila = threading.Lock()  # protege a fila e o dict de status
status = {}  # status[bebe_id]

def criar_necessidades(bebe_id):
    return {
        "bebe_id": bebe_id,
        "tipo": random.choice(TIPOS_NECESSIDADES),
        "timestamp": time.time(),
    }

def rotina_bebe(bebe_id):
    global rodando
    while rodando:
        tempo = random.uniform(0.5, 3.0) #Espera um tempo aleatório
        time.sleep(tempo)
        if not rodando:
            break
        print(f"Bebe {bebe_id} chorou depois de {tempo:.2f}s")
        fila.append(bebe_id)

def rotina_cuidadora(cuidadora_id):
    while rodando or fila:  # continua drenando a fila mesmo após o tempo acabar
        with lock_fila:
            item = fila.pop(0) if fila else None
            if item:
                status[item["bebe_id"]] = "sendo atendido"

        if item:
            tempo_espera = time.time() - item["timestamp"]
            print(f"Cuidadora {cuidadora_id} atendendo bebe {item['bebe_id']} "
                  f"({item['tipo']}), esperou {tempo_espera:.2f}s")
            time.sleep(random.uniform(0.3, 1.5))  # tempo de atendimento, fora do lock
            with lock_fila:
                status[item["bebe_id"]] = "calmo"
                atendimentos.append((item["bebe_id"], item["tipo"], tempo_espera))
        else:
            time.sleep(0.1)  # evita busy-wait quando a fila está vazia

num_bebes = int(sys.argv[1])
tempo_rodar = int(sys.argv[2])
#Cria os bebês apartir do argumento passado na hora de rodar o arquivo
threads = []
for i in range(num_bebes):
    t = threading.Thread(target=rotina_bebe, args=(i,))
    threads.append(t)
    t.start()  # dispara a thread — ela já começa a rodar em paralelo

time.sleep(tempo_rodar)
rodando = False

#Espera todas terminarem antes do programa fechar
for t in threads:
    t.join(timeout=2)

print(f"\n Fila final tem {len(fila)} necessidade(s) do(s) bebe(s) esperando a cuidadora: {fila}")
for i in range(num_bebes):
    print(f"Bebê {i} teve {fila.count(i)} necessidade(s).")