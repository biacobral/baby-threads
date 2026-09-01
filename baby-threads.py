import threading
import time
import random
import sys

fila = []#Lista compartilhada das Threads
rodando = True#Flag para sinalizar se para ou não

def rotina_bebe(bebe_id):
    global rodando
    while rodando:
        tempo = random.uniform(0.5, 3.0) #Espera um tempo aleatório
        time.sleep(tempo)
        if not rodando:
            break
        print(f"Bebe {bebe_id} chorou depois de {tempo:.2f}s")
        fila.append(bebe_id)

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