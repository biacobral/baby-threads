#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Baby Threads - Interface Gráfica (Tkinter)
Disciplina: Sistemas Operacionais (C12) - Inatel

Este arquivo NÃO altera a simulação. Ele importa o `baby-threads.py` original,
dispara as mesmas threads de bebês e cuidadoras e apenas substitui a thread de
renderização em texto (TUI) por uma cena gráfica:

  - Cuidadoras ficam no centro da sala;
  - Berços com os bebês ficam espalhados em volta;
  - Quando uma cuidadora pega um chamado, o bebê "anda" até o lado dela e volta
    para o berço quando o atendimento termina;
  - Log de eventos e problemas de concorrência ficam num painel lateral.

Assim como a TUI original, a interface lê as estruturas compartilhadas SEM locks.
Quando uma leitura falha por causa de uma escrita concorrente, o erro é contado
na mesma métrica `erros_concorrencia_tui`, para que a interface também seja uma
"vítima" visível das condições de corrida.

Uso:
    python baby-threads-gui.py <NUM_BEBES> <NUM_CUIDADORAS> <TEMPO_SIMULACAO>
Exemplo:
    python baby-threads-gui.py 5 2 15
"""

import contextlib
import importlib.util
import io
import math
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk


# ==============================================================================
# CARREGA A SIMULAÇÃO ORIGINAL COMO MÓDULO (o nome do arquivo tem hífen)
# ==============================================================================
def carregar_simulacao():
    caminho = os.path.join(os.path.dirname(os.path.abspath(__file__)), "baby-threads.py")
    if not os.path.exists(caminho):
        print("Erro: baby-threads.py não encontrado ao lado de baby-threads-gui.py")
        sys.exit(1)
    spec = importlib.util.spec_from_file_location("baby_threads", caminho)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)  # executa a validação de argumentos e a inicialização dos estados
    return modulo


sim = carregar_simulacao()


# ==============================================================================
# PALETA E CONSTANTES VISUAIS
# ==============================================================================
FONTE = "Segoe UI"
FONTE_MONO = "Consolas"

COR_FUNDO = "#F4F5F7"
COR_SALA = "#FBFBFD"
COR_TAPETE = "#EEF1F6"
COR_PAINEL = "#FFFFFF"
COR_TEXTO = "#1F2933"
COR_TEXTO_SUAVE = "#7B8794"
COR_BORDA = "#D9DEE3"

# estado -> (fundo claro, cor forte, texto, símbolo)
ESTADOS_BEBE = {
    "DORMINDO":       ("#E3F6E8", "#2F9E5B", "dormindo", "zZ"),
    "BRINCANDO":      ("#FFF6D6", "#D69E00", "brincando", "♪"),
    "CHORANDO":       ("#FFE1E1", "#D64545", "CHORANDO", "!"),
    "SENDO_ATENDIDO": ("#DDEBFF", "#2F6FD6", "sendo atendido", "♥"),
}

COR_CUIDADORA_OCIOSA = "#9AA5B1"
COR_CUIDADORA_ATIVA = "#2F6FD6"

CORES_NECESSIDADE = {
    "fome":    "#F97316",
    "fralda":  "#A855F7",
    "sono":    "#6366F1",
    "higiene": "#14B8A6",
}

COR_ERRO = "#D64545"
COR_ALERTA = "#D69E00"

INTERVALO_FRAME_MS = 40          # ~25 quadros por segundo
VELOCIDADE_ANIMACAO = 0.18       # fração do caminho percorrida por quadro

BERCO_W, BERCO_H = 158, 98
RAIO_BEBE = 19
RAIO_CUIDADORA = 30
DESLOC_SLOT = 82                 # distância do centro da cuidadora até o "colo" onde o bebê fica


def rrect(cv, x1, y1, x2, y2, r=10, **kw):
    """Retângulo de cantos arredondados no Canvas."""
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return cv.create_polygon(pts, smooth=True, **kw)


# ==============================================================================
# APLICAÇÃO
# ==============================================================================
class BabyThreadsApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Baby Threads - Berçário Virtual Concorrente [SEM SINCRONIZAÇÃO]")
        self.root.configure(bg=COR_FUNDO)
        self.root.minsize(1100, 700)
        self.root.protocol("WM_DELETE_WINDOW", self.fechar)

        self.encerrando = False
        self.threads = []

        # Memória do último estado observado, para detectar eventos
        self.metricas_anteriores = dict(sim.metricas)
        self.starv_anteriores = {i: 0 for i in range(sim.num_bebes)}
        self.alvo_anterior_cuidadora = {j: None for j in range(sim.num_cuidadoras)}

        # Geometria da cena
        self.pos_berco = {}        # bebe_id -> (x, y) centro do berço
        self.pos_cuidadora = {}    # cuidadora_id -> (x, y)
        self.pos_bebe = {}         # bebe_id -> [x, y] posição animada do avatar
        self.banners = []          # (texto, cor, expira_em)
        self.layout_pronto = False

        self._montar_cabecalho()
        self._montar_corpo()

    # --------------------------------------------------------------------------
    # CONSTRUÇÃO
    # --------------------------------------------------------------------------
    def _montar_cabecalho(self):
        topo = tk.Frame(self.root, bg=COR_FUNDO)
        topo.pack(fill="x", padx=14, pady=(8, 2))

        tk.Label(topo, text="BABY THREADS", font=(FONTE, 17, "bold"),
                 fg=COR_TEXTO, bg=COR_FUNDO).pack(side="left")
        tk.Label(topo, text="  berçário virtual concorrente  ·  modo SEM sincronização  ·  "
                            f"{sim.num_bebes} bebês, {sim.num_cuidadoras} cuidadoras, "
                            f"{sim.num_bebes + sim.num_cuidadoras + 1} threads",
                 font=(FONTE, 10), fg=COR_TEXTO_SUAVE, bg=COR_FUNDO).pack(side="left", pady=(5, 0))

        direita = tk.Frame(topo, bg=COR_FUNDO)
        direita.pack(side="right")
        self.lbl_tempo = tk.Label(direita, text=f"0.0s / {sim.tempo_simulacao}s",
                                  font=(FONTE_MONO, 13, "bold"), fg=COR_TEXTO, bg=COR_FUNDO)
        self.lbl_tempo.pack(side="right")
        self.barra_tempo = ttk.Progressbar(direita, length=220, maximum=sim.tempo_simulacao, mode="determinate")
        self.barra_tempo.pack(side="right", padx=(0, 10), pady=(4, 0))

    def _montar_corpo(self):
        corpo = tk.Frame(self.root, bg=COR_FUNDO)
        corpo.pack(fill="both", expand=True, padx=14, pady=(4, 12))

        # ---- cena (esquerda) ----
        moldura = tk.Frame(corpo, bg=COR_PAINEL, highlightbackground=COR_BORDA, highlightthickness=1)
        moldura.pack(side="left", fill="both", expand=True)
        self.cv = tk.Canvas(moldura, bg=COR_SALA, highlightthickness=0)
        self.cv.pack(fill="both", expand=True)
        self.cv.bind("<Configure>", self._ao_redimensionar)

        # ---- painel lateral (direita) ----
        lateral = tk.Frame(corpo, bg=COR_FUNDO, width=380)
        lateral.pack(side="right", fill="y", padx=(10, 0))
        lateral.pack_propagate(False)

        painel_log = tk.Frame(lateral, bg=COR_PAINEL, highlightbackground=COR_BORDA, highlightthickness=1)
        painel_log.pack(fill="both", expand=True)
        tk.Label(painel_log, text="LOG DE EVENTOS", font=(FONTE, 9, "bold"), fg=COR_TEXTO_SUAVE,
                 bg=COR_PAINEL, anchor="w").pack(fill="x", padx=10, pady=(6, 2))
        self.log = tk.Text(painel_log, font=(FONTE_MONO, 9), bg="#1F2933", fg="#E4E7EB",
                           relief="flat", state="disabled", wrap="word", padx=6, pady=4)
        self.log.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.log.tag_configure("erro", foreground="#FF8A8A")
        self.log.tag_configure("alerta", foreground="#FFD166")
        self.log.tag_configure("ok", foreground="#8FD3A8")
        self.log.tag_configure("info", foreground="#9AA5B1")

        # ---- problemas de concorrência, discretos, abaixo do log ----
        painel_m = tk.Frame(lateral, bg=COR_PAINEL, highlightbackground=COR_BORDA, highlightthickness=1)
        painel_m.pack(fill="x", pady=(8, 0))
        tk.Label(painel_m, text="PROBLEMAS DE CONCORRÊNCIA", font=(FONTE, 9, "bold"), fg=COR_TEXTO_SUAVE,
                 bg=COR_PAINEL, anchor="w").pack(fill="x", padx=10, pady=(6, 2))

        self.metric_labels = {}
        definicoes = [
            ("conflitos_fila_pop", "Condições de corrida na fila (pop em fila vazia)"),
            ("erros_concorrencia_tui", "Leituras inconsistentes na interface"),
            ("total_starvations", f"Starvations (> {sim.LIMITE_STARVATION:.0f}s chorando)"),
        ]
        for chave, texto in definicoes:
            linha = tk.Frame(painel_m, bg=COR_PAINEL)
            linha.pack(fill="x", padx=10, pady=1)
            tk.Label(linha, text=texto, font=(FONTE, 9), fg=COR_TEXTO, bg=COR_PAINEL, anchor="w").pack(side="left")
            valor = tk.Label(linha, text="0", font=(FONTE_MONO, 11, "bold"), fg=COR_TEXTO, bg=COR_PAINEL, width=4, anchor="e")
            valor.pack(side="right")
            self.metric_labels[chave] = valor

        self.lbl_balanco = tk.Label(painel_m, text="gerados 0 · atendidos 0 · na fila 0",
                                    font=(FONTE, 8), fg=COR_TEXTO_SUAVE, bg=COR_PAINEL, anchor="w")
        self.lbl_balanco.pack(fill="x", padx=10, pady=(4, 8))

    # --------------------------------------------------------------------------
    # GEOMETRIA DA CENA
    # --------------------------------------------------------------------------
    def _ao_redimensionar(self, _evento=None):
        self._calcular_layout()

    def _calcular_layout(self):
        W = max(self.cv.winfo_width(), 400)
        H = max(self.cv.winfo_height(), 300)
        cx, cy = W / 2, H / 2 + 10

        # Cuidadoras no centro, em uma grade compacta
        n_c = sim.num_cuidadoras
        colunas = min(n_c, 3)
        linhas = math.ceil(n_c / colunas)
        esp_x, esp_y = 230, 150
        for j in range(n_c):
            lin, col = divmod(j, colunas)
            n_na_linha = colunas if lin < linhas - 1 else n_c - lin * colunas
            x = cx + (col - (n_na_linha - 1) / 2) * esp_x - DESLOC_SLOT / 2
            y = cy + (lin - (linhas - 1) / 2) * esp_y
            self.pos_cuidadora[j] = (x, y)

        # Berços espalhados em uma elipse ao redor
        rx = W / 2 - BERCO_W / 2 - 36
        ry = H / 2 - BERCO_H / 2 - 52
        n_b = sim.num_bebes
        for i in range(n_b):
            ang = -math.pi / 2 + (2 * math.pi * i) / n_b
            x = cx + rx * math.cos(ang)
            y = cy + ry * math.sin(ang) - 6
            self.pos_berco[i] = (x, y)
            if i not in self.pos_bebe:
                self.pos_bebe[i] = list(self._pos_no_berco(i))

        self.layout_pronto = True

    def _pos_no_berco(self, i):
        """Posição do avatar do bebê quando ele está deitado no próprio berço."""
        bx, by = self.pos_berco[i]
        return (bx - BERCO_W / 2 + 30, by + 2)

    def _alvo_do_bebe(self, i, cuidadora_do_bebe):
        """Onde o avatar do bebê deve estar neste quadro."""
        if cuidadora_do_bebe is not None:
            cxj, cyj = self.pos_cuidadora[cuidadora_do_bebe]
            return (cxj + DESLOC_SLOT, cyj)
        return self._pos_no_berco(i)

    # --------------------------------------------------------------------------
    # LOG E BANNERS
    # --------------------------------------------------------------------------
    def registrar(self, texto, tag="info"):
        decorrido = time.time() - sim.tempo_inicio
        self.log.configure(state="normal")
        self.log.insert("end", f"{decorrido:5.1f}s  {texto}\n", tag)
        linhas = int(self.log.index("end-1c").split(".")[0])
        if linhas > 300:
            self.log.delete("1.0", "50.0")
        self.log.see("end")
        self.log.configure(state="disabled")

    def banner(self, texto, cor, duracao=1.6):
        self.banners.append((texto, cor, time.time() + duracao))
        self.banners = self.banners[-3:]

    def piscar_metrica(self, chave, cor):
        lbl = self.metric_labels[chave]
        lbl.configure(fg=cor)
        self.root.after(600, lambda: lbl.configure(fg=COR_TEXTO))

    # --------------------------------------------------------------------------
    # CONTROLE DA SIMULAÇÃO
    # --------------------------------------------------------------------------
    def iniciar(self):
        sim.tempo_inicio = time.time()
        for i in range(sim.num_bebes):
            t = threading.Thread(target=sim.rotina_bebe, args=(i,), daemon=True)
            self.threads.append(t)
            t.start()
        for j in range(sim.num_cuidadoras):
            t = threading.Thread(target=sim.rotina_cuidadora, args=(j,), daemon=True)
            self.threads.append(t)
            t.start()
        self.registrar(f"Simulação iniciada: {sim.num_bebes} bebês, {sim.num_cuidadoras} cuidadoras, "
                       f"{sim.tempo_simulacao}s", "ok")
        self.root.after(INTERVALO_FRAME_MS, self.quadro)

    def quadro(self):
        """Um quadro de animação: lê o estado compartilhado (sem lock) e redesenha."""
        try:
            if not self.layout_pronto:
                self._calcular_layout()
            decorrido = time.time() - sim.tempo_inicio
            self.lbl_tempo.configure(text=f"{decorrido:5.1f}s / {sim.tempo_simulacao}s")
            self.barra_tempo["value"] = min(decorrido, sim.tempo_simulacao)
            self._detectar_eventos()
            self._desenhar()
        except Exception:
            # Mesma semântica da TUI original: leitura concorrente inconsistente
            sim.metricas["erros_concorrencia_tui"] += 1

        if not self.encerrando:
            if time.time() - sim.tempo_inicio >= sim.tempo_simulacao:
                self.finalizar()
            else:
                self.root.after(INTERVALO_FRAME_MS, self.quadro)

    # --------------------------------------------------------------------------
    # DETECÇÃO DE EVENTOS (log, banners, métricas)
    # --------------------------------------------------------------------------
    def _detectar_eventos(self):
        m = sim.metricas
        limite = sim.LIMITE_STARVATION

        for j in range(sim.num_cuidadoras):
            c = sim.status_cuidadoras[j]
            alvo = c["atendendo_bebe"]
            if alvo is not None and alvo != self.alvo_anterior_cuidadora[j]:
                self.registrar(f"Cuidadora #{j:02d} pegou Bebê #{alvo:02d} ({c['necessidade_atual']})", "ok")
            self.alvo_anterior_cuidadora[j] = alvo

        for i in range(sim.num_bebes):
            b = sim.status_bebes[i]
            if b["starvation_count"] > self.starv_anteriores[i]:
                self.starv_anteriores[i] = b["starvation_count"]
                self.registrar(f"STARVATION: Bebê #{i:02d} chora há mais de {limite:.0f}s ({b['necessidade']})", "alerta")
                self.banner(f"STARVATION  ·  Bebê #{i:02d} está sendo ignorado", COR_ALERTA)

        if m["conflitos_fila_pop"] > self.metricas_anteriores["conflitos_fila_pop"]:
            self.registrar("RACE CONDITION: duas cuidadoras disputaram o mesmo chamado (pop em fila vazia)", "erro")
            self.banner("RACE CONDITION  ·  duas cuidadoras pegaram o mesmo chamado", COR_ERRO)
            self.piscar_metrica("conflitos_fila_pop", COR_ERRO)
        if m["erros_concorrencia_tui"] > self.metricas_anteriores["erros_concorrencia_tui"]:
            self.registrar("LEITURA INCONSISTENTE: a interface leu uma estrutura em plena alteração", "erro")
            self.piscar_metrica("erros_concorrencia_tui", COR_ERRO)
        if m["total_starvations"] > self.metricas_anteriores["total_starvations"]:
            self.piscar_metrica("total_starvations", COR_ALERTA)

        for chave, lbl in self.metric_labels.items():
            lbl.configure(text=str(m[chave]))
            self.metricas_anteriores[chave] = m[chave]
        self.lbl_balanco.configure(
            text=f"gerados {m['total_pedidos_gerados']} · atendidos {m['total_pedidos_atendidos']} · na fila {len(sim.fila)}")

    # --------------------------------------------------------------------------
    # DESENHO DA CENA
    # --------------------------------------------------------------------------
    def _desenhar(self):
        cv = self.cv
        cv.delete("all")
        W, H = cv.winfo_width(), cv.winfo_height()
        agora = time.time()

        # quem está com quem
        cuidadora_do_bebe = {}
        for j in range(sim.num_cuidadoras):
            c = sim.status_cuidadoras[j]
            if c["estado"] == "ATENDENDO" and c["atendendo_bebe"] is not None:
                cuidadora_do_bebe[c["atendendo_bebe"]] = j

        self._desenhar_tapete(W, H)
        self._desenhar_fila(W)
        self._desenhar_bercos(cuidadora_do_bebe, agora)
        self._desenhar_cuidadoras(cuidadora_do_bebe)
        self._desenhar_bebes(cuidadora_do_bebe)
        self._desenhar_banners(W, H, agora)

    def _desenhar_tapete(self, W, H):
        # "tapete" central onde as cuidadoras trabalham
        xs = [p[0] for p in self.pos_cuidadora.values()]
        ys = [p[1] for p in self.pos_cuidadora.values()]
        if xs:
            x1, x2 = min(xs) - 90, max(xs) + DESLOC_SLOT + 70
            y1, y2 = min(ys) - 85, max(ys) + 85
            rrect(self.cv, x1, y1, x2, y2, r=28, fill=COR_TAPETE, outline="")
            self.cv.create_text(x1 + 14, y1 + 10, text="CUIDADORAS  ·  threads consumidoras", anchor="nw",
                                font=(FONTE, 8, "bold"), fill=COR_TEXTO_SUAVE)

    def _desenhar_fila(self, W):
        snapshot = list(sim.fila)
        cv = self.cv
        y = 8
        cv.create_text(12, y + 13, text="FILA COMPARTILHADA", anchor="w", font=(FONTE, 8, "bold"), fill=COR_TEXTO_SUAVE)
        x = 150
        if not snapshot:
            cv.create_text(x, y + 13, text="vazia", anchor="w", font=(FONTE, 9), fill=COR_TEXTO_SUAVE)
            return
        chip_w, chip_h, gap = 92, 24, 6
        for idx, pedido in enumerate(snapshot):
            if x + chip_w > W - 70:
                cv.create_text(x + 4, y + 13, text=f"+{len(snapshot) - idx}", anchor="w",
                               font=(FONTE, 10, "bold"), fill=COR_TEXTO_SUAVE)
                break
            cor = CORES_NECESSIDADE.get(pedido["tipo"], "#999999")
            rrect(cv, x, y, x + chip_w, y + chip_h, r=12, fill=cor, outline="")
            cv.create_text(x + chip_w / 2, y + chip_h / 2, text=f"B{pedido['bebe_id']:02d} · {pedido['tipo']}",
                           fill="white", font=(FONTE, 9, "bold"))
            x += chip_w + gap
        cv.create_text(150, y + chip_h + 10, text="◀ próximo a ser pego", anchor="w", font=(FONTE, 7), fill=COR_TEXTO_SUAVE)

    def _desenhar_bercos(self, cuidadora_do_bebe, agora):
        cv = self.cv
        limite = sim.LIMITE_STARVATION
        for i in range(sim.num_bebes):
            b = sim.status_bebes[i]
            bx, by = self.pos_berco[i]
            x1, y1 = bx - BERCO_W / 2, by - BERCO_H / 2
            x2, y2 = bx + BERCO_W / 2, by + BERCO_H / 2
            estado = b["estado"]
            fundo, forte, texto_estado, _ = ESTADOS_BEBE.get(estado, ESTADOS_BEBE["DORMINDO"])

            espera = b["tempo_espera_atual"] if estado == "CHORANDO" else 0.0
            em_starvation = espera >= limite
            if em_starvation and int(agora * 4) % 2 == 0:
                rrect(cv, x1 - 5, y1 - 5, x2 + 5, y2 + 5, r=16, fill="#FFC9C9", outline="")

            rrect(cv, x1, y1, x2, y2, r=12, fill=fundo,
                  outline=(COR_ERRO if em_starvation else forte), width=(3 if em_starvation else 1.5))

            cv.create_text(x1 + 10, y1 + 12, text=f"Berço #{i:02d}", anchor="w", font=(FONTE, 8), fill=COR_TEXTO_SUAVE)
            cv.create_text(x2 - 10, y1 + 12, text=("STARVATION!" if em_starvation else texto_estado), anchor="e",
                           font=(FONTE, 8, "bold"), fill=(COR_ERRO if em_starvation else forte))

            # lugar do bebê (vazio quando ele está no colo da cuidadora)
            if i in cuidadora_do_bebe:
                cv.create_oval(bx - 30 - RAIO_BEBE, by + 4 - RAIO_BEBE, bx - 30 + RAIO_BEBE, by + 4 + RAIO_BEBE,
                               outline=COR_BORDA, dash=(3, 3), width=1.5)
                cv.create_text(bx - 4, by + 4, text=f"com a\ncuidadora #{cuidadora_do_bebe[i]:02d}", anchor="w",
                               font=(FONTE, 8), fill=COR_TEXTO_SUAVE)
            else:
                nec = b["necessidade"]
                if nec:
                    cv.create_text(bx - 4, by + 4, text=f"● {nec}", anchor="w", font=(FONTE, 10, "bold"),
                                   fill=CORES_NECESSIDADE.get(nec, COR_TEXTO))
                else:
                    cv.create_text(bx - 4, by + 4, text=texto_estado, anchor="w", font=(FONTE, 9), fill=COR_TEXTO_SUAVE)

            # barra de espera
            bar_x1, bar_x2, bar_y = x1 + 10, x2 - 10, y2 - 11
            cv.create_rectangle(bar_x1, bar_y, bar_x2, bar_y + 6, fill="#E4E7EB", outline="")
            if espera > 0:
                frac = min(espera / limite, 1.0)
                cor_barra = COR_ERRO if frac >= 1 else (COR_ALERTA if frac >= 0.6 else "#2F9E5B")
                cv.create_rectangle(bar_x1, bar_y, bar_x1 + (bar_x2 - bar_x1) * frac, bar_y + 6, fill=cor_barra, outline="")
                cv.create_text(bar_x2, bar_y - 3, text=f"{espera:3.1f}s", anchor="se", font=(FONTE_MONO, 7),
                               fill=(COR_ERRO if frac >= 1 else COR_TEXTO_SUAVE))
            cv.create_text(bar_x1, bar_y - 3, text=f"{b['total_atendidos']} atend · {b['starvation_count']} starv",
                           anchor="sw", font=(FONTE, 7), fill=COR_TEXTO_SUAVE)

    def _desenhar_cuidadoras(self, cuidadora_do_bebe):
        cv = self.cv
        for j in range(sim.num_cuidadoras):
            c = sim.status_cuidadoras[j]
            x, y = self.pos_cuidadora[j]
            ativa = c["estado"] == "ATENDENDO"
            cor = COR_CUIDADORA_ATIVA if ativa else COR_CUIDADORA_OCIOSA

            # colo (onde o bebê é encaixado)
            sx, sy = x + DESLOC_SLOT, y
            cv.create_oval(sx - RAIO_BEBE - 5, sy - RAIO_BEBE - 5, sx + RAIO_BEBE + 5, sy + RAIO_BEBE + 5,
                           outline=(cor if ativa else COR_BORDA), dash=(() if ativa else (3, 3)), width=1.5,
                           fill=("#EAF1FC" if ativa else COR_SALA))
            if not ativa:
                cv.create_text(sx, sy, text="livre", font=(FONTE, 7), fill=COR_TEXTO_SUAVE)

            # ligação cuidadora -> colo
            cv.create_line(x + RAIO_CUIDADORA, y, sx - RAIO_BEBE - 5, sy, fill=cor, width=2)

            # a cuidadora
            cv.create_oval(x - RAIO_CUIDADORA - 4, y - RAIO_CUIDADORA - 4, x + RAIO_CUIDADORA + 4, y + RAIO_CUIDADORA + 4,
                           fill=("#DDEBFF" if ativa else "#EEF0F3"), outline="")
            cv.create_oval(x - RAIO_CUIDADORA, y - RAIO_CUIDADORA, x + RAIO_CUIDADORA, y + RAIO_CUIDADORA,
                           fill=cor, outline="white", width=2)
            cv.create_text(x, y, text=f"C{j:02d}", fill="white", font=(FONTE, 12, "bold"))

            cv.create_text(x, y + RAIO_CUIDADORA + 14, text=f"Cuidadora #{j:02d}", font=(FONTE, 9, "bold"), fill=COR_TEXTO)
            cv.create_text(x, y + RAIO_CUIDADORA + 28,
                           text=(f"atendendo · {c['total_atendidos']} feitos" if ativa else f"ociosa · {c['total_atendidos']} feitos"),
                           font=(FONTE, 8), fill=(cor if ativa else COR_TEXTO_SUAVE))

            # balão com a necessidade que está sendo atendida
            if ativa and c["necessidade_atual"]:
                nec = c["necessidade_atual"]
                cor_nec = CORES_NECESSIDADE.get(nec, COR_TEXTO)
                bx1, by1 = sx - 34, sy - RAIO_BEBE - 36
                rrect(cv, bx1, by1, bx1 + 68, by1 + 20, r=10, fill=cor_nec, outline="")
                cv.create_polygon(sx - 5, by1 + 20, sx + 5, by1 + 20, sx, by1 + 27, fill=cor_nec, outline="")
                cv.create_text(sx, by1 + 10, text=nec, fill="white", font=(FONTE, 8, "bold"))

    def _desenhar_bebes(self, cuidadora_do_bebe):
        cv = self.cv
        for i in range(sim.num_bebes):
            b = sim.status_bebes[i]
            estado = b["estado"]
            _, forte, _, simbolo = ESTADOS_BEBE.get(estado, ESTADOS_BEBE["DORMINDO"])

            # animação: aproxima a posição atual do alvo
            tx, ty = self._alvo_do_bebe(i, cuidadora_do_bebe.get(i))
            p = self.pos_bebe[i]
            p[0] += (tx - p[0]) * VELOCIDADE_ANIMACAO
            p[1] += (ty - p[1]) * VELOCIDADE_ANIMACAO
            x, y = p

            em_movimento = abs(tx - x) > 1.5 or abs(ty - y) > 1.5
            if em_movimento:
                cv.create_oval(x - RAIO_BEBE - 6, y - RAIO_BEBE - 6, x + RAIO_BEBE + 6, y + RAIO_BEBE + 6,
                               fill="", outline=forte, dash=(2, 4))

            cv.create_oval(x - RAIO_BEBE, y - RAIO_BEBE, x + RAIO_BEBE, y + RAIO_BEBE,
                           fill=forte, outline="white", width=2)
            cv.create_text(x, y - 3, text=f"B{i:02d}", fill="white", font=(FONTE, 9, "bold"))
            cv.create_text(x, y + 9, text=simbolo, fill="white", font=(FONTE, 7, "bold"))

    def _desenhar_banners(self, W, H, agora):
        self.banners = [bn for bn in self.banners if bn[2] > agora]
        y = 48
        for texto, cor, _ in self.banners:
            largura = 9 * len(texto) + 40
            x1 = W / 2 - largura / 2
            rrect(self.cv, x1, y, x1 + largura, y + 28, r=14, fill=cor, outline="")
            self.cv.create_text(W / 2, y + 14, text=texto, fill="white", font=(FONTE, 10, "bold"))
            y += 34

    # --------------------------------------------------------------------------
    # ENCERRAMENTO E RELATÓRIO
    # --------------------------------------------------------------------------
    def finalizar(self):
        if self.encerrando:
            return
        self.encerrando = True
        sim.rodando = False
        self.registrar("Tempo esgotado. Encerrando threads...", "info")
        self.lbl_tempo.configure(text=f"{sim.tempo_simulacao}s / {sim.tempo_simulacao}s  ✔")
        self.root.after(300, self.mostrar_relatorio)

    def mostrar_relatorio(self):
        for t in self.threads:
            t.join(timeout=1.0)

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            sim.exibir_relatorio_final()
        relatorio = buffer.getvalue()
        print(relatorio, flush=True)  # mantém o relatório também no terminal, como no original

        try:
            self._detectar_eventos()
            self._desenhar()
        except Exception:
            pass

        janela = tk.Toplevel(self.root)
        janela.title("Relatório Final da Simulação")
        janela.configure(bg=COR_PAINEL)
        janela.geometry("860x720")
        area = tk.Frame(janela, bg=COR_PAINEL)
        area.pack(fill="both", expand=True, padx=10, pady=10)
        texto = tk.Text(area, font=(FONTE_MONO, 10), bg="#1F2933", fg="#E4E7EB", relief="flat", wrap="none")
        rolagem = ttk.Scrollbar(area, orient="vertical", command=texto.yview)
        texto.configure(yscrollcommand=rolagem.set)
        rolagem.pack(side="right", fill="y")
        texto.pack(side="left", fill="both", expand=True)
        texto.insert("1.0", relatorio)
        texto.configure(state="disabled")
        tk.Button(janela, text="Fechar tudo", font=(FONTE, 10, "bold"), command=self.fechar,
                  bg="#2F6FD6", fg="white", relief="flat", padx=16, pady=6).pack(pady=(0, 10))
        janela.lift()

    def fechar(self):
        sim.rodando = False
        self.encerrando = True
        self.root.destroy()


# ==============================================================================
# PONTO DE ENTRADA
# ==============================================================================
def main():
    root = tk.Tk()
    try:
        root.state("zoomed")  # abre maximizada no Windows
    except tk.TclError:
        pass
    app = BabyThreadsApp(root)
    root.after(500, app.iniciar)  # meio segundo para a janela desenhar antes das threads começarem
    root.mainloop()


if __name__ == "__main__":
    main()
