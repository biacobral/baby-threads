#!/usr/bin/env python3
"""Painel Tkinter para comparar políticas, sem dependências externas."""

import csv
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import comparacao as motor


FUNDO = "#F3F5FA"
TEXTO = "#18243C"
SUAVE = "#64748B"
CORES = {"sync": "#4F46E5", "sem-sync": "#F59E0B"}
NOMES = {"fifo": "FIFO", "sjf": "SJF", "priority": "Prioridade"}
METRICAS = {
    "Espera média (s)": ("espera_media", "Menor é melhor · pedidos concluídos"),
    "Atendimentos": ("atendidos", "Maior é melhor · média por execução"),
    "Espera p95 (s)": ("espera_p95", "Menor é melhor · pedidos concluídos"),
    "Espera máxima (s)": ("espera_max", "Inclui pedidos restantes na fila"),
    "Starvations": ("starvations", "Episódios acima do limite de espera da simulação"),
    "Conflitos na fila": ("conflitos_fila", "Menor é melhor · média por execução"),
    "Contadores divergentes": ("contadores_divergentes", "Menor é melhor · soma das diferenças entre contadores"),
}


class ComparacaoApp:
    def __init__(self, root):
        self.root = root
        self.eventos = queue.Queue()
        self.cancelar = threading.Event()
        self.executando = False
        self.linhas = []
        self.resultados = {caso: [] for caso in motor.CASOS}
        root.title("Baby Threads · Comparação de políticas")
        root.geometry("1180x850")
        root.minsize(1000, 760)
        root.configure(bg=FUNDO)
        root.protocol("WM_DELETE_WINDOW", self.fechar)
        estilo = ttk.Style(root)
        estilo.theme_use("clam")
        estilo.configure("TFrame", background=FUNDO)
        estilo.configure("TLabel", background=FUNDO, foreground=TEXTO, font=("Segoe UI", 10))
        estilo.configure("Title.TLabel", font=("Segoe UI", 25, "bold"))
        estilo.configure("Muted.TLabel", foreground=SUAVE)
        estilo.configure("TButton", font=("Segoe UI", 10), padding=(14, 8))
        estilo.configure("Accent.TButton", background=CORES["sync"], foreground="white")
        estilo.configure("Treeview", font=("Segoe UI", 10), rowheight=32, background="white", fieldbackground="white")
        estilo.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"), padding=8)

        pagina = ttk.Frame(root, padding=24)
        pagina.pack(fill="both", expand=True)
        ttk.Label(pagina, text="Laboratório de comparação", style="Title.TLabel").pack(anchor="w")
        ttk.Label(pagina, text="BABY THREADS  /  FIFO, SJF e prioridade · com e sem sincronização", style="Muted.TLabel").pack(anchor="w", pady=(4, 20))

        config = ttk.Frame(pagina)
        config.pack(fill="x")
        self.campos = {}
        self.entradas = []
        for coluna, (nome, valor) in enumerate((("Bebês", 12), ("Cuidadoras", 2), ("Duração (s)", 20), ("Repetições", 5))):
            bloco = ttk.Frame(config)
            bloco.grid(row=0, column=coluna, padx=(0, 18), sticky="w")
            ttk.Label(bloco, text=nome).pack(anchor="w", pady=(0, 5))
            var = tk.StringVar(value=str(valor))
            entrada = ttk.Spinbox(bloco, from_=1, to=10000, textvariable=var, width=10)
            entrada.pack()
            self.campos[nome] = var
            self.entradas.append(entrada)
        self.iniciar_btn = ttk.Button(config, text="Iniciar comparação", style="Accent.TButton", command=self.iniciar)
        self.iniciar_btn.grid(row=0, column=4, sticky="s", padx=(0, 8))
        self.parar_btn = ttk.Button(config, text="Parar", command=self.parar, state="disabled")
        self.parar_btn.grid(row=0, column=5, sticky="s")

        self.status = tk.StringVar(value="Configure o cenário e inicie. As seis combinações serão executadas em cada repetição.")
        ttk.Label(pagina, textvariable=self.status, style="Muted.TLabel").pack(anchor="w", pady=(18, 7))
        self.progresso = ttk.Progressbar(pagina, mode="determinate")
        self.progresso.pack(fill="x", pady=(0, 18))

        cards = ttk.Frame(pagina)
        cards.pack(fill="x", pady=(0, 16))
        self.cards = []
        for coluna, titulo in enumerate(("REPETIÇÕES CONCLUÍDAS", "ATENDIMENTOS · MÉDIA DOS 6 CASOS", "CONFLITOS · MÉDIA DOS 6 CASOS")):
            cards.columnconfigure(coluna, weight=1)
            card = tk.Frame(cards, bg="white", padx=16, pady=12)
            card.grid(row=0, column=coluna, sticky="ew", padx=(0, 10 if coluna < 2 else 0))
            tk.Label(card, text=titulo, bg="white", fg=SUAVE, font=("Segoe UI", 9)).pack(anchor="w")
            numero = tk.Label(card, text="—", bg="white", fg=TEXTO, font=("Segoe UI", 23, "bold"))
            numero.pack(anchor="w")
            self.cards.append(numero)

        topo = ttk.Frame(pagina)
        topo.pack(fill="x")
        ttk.Label(topo, text="Comparação por política", font=("Segoe UI", 14, "bold")).pack(side="left")
        self.metrica = tk.StringVar(value=next(iter(METRICAS)))
        seletor = ttk.Combobox(topo, textvariable=self.metrica, values=list(METRICAS), state="readonly", width=28)
        seletor.pack(side="right")
        seletor.bind("<<ComboboxSelected>>", lambda _: self.desenhar())
        self.canvas = tk.Canvas(pagina, bg="white", height=245, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, pady=(10, 5))
        self.canvas.bind("<Configure>", lambda _: self.desenhar())
        self.nota = tk.StringVar()
        ttk.Label(pagina, textvariable=self.nota, style="Muted.TLabel").pack(anchor="w", pady=(0, 12))

        abas = ttk.Notebook(pagina)
        abas.pack(fill="x")
        self.tabelas = []
        grupos = [
            ("Desempenho", [("atendidos", "Atendidos"), ("espera_media", "Espera média (s)"), ("espera_p95", "P95 (s)"), ("espera_max", "Máxima (s)"), ("pendentes", "Fila final"), ("utilizacao", "Utilização estim.")]),
            ("Concorrência", [("conflitos_fila", "Conflitos na fila"), ("contadores_divergentes", "Divergências"), ("starvations", "Starvations")]),
            ("Necessidades", [(f"espera_{tipo}", f"{tipo.capitalize()} (s)") for tipo in motor.NECESSIDADES]),
        ]
        for titulo, colunas in grupos:
            frame = ttk.Frame(abas)
            abas.add(frame, text=titulo)
            tabela = ttk.Treeview(frame, columns=["modo", "politica"] + [k for k, _ in colunas], show="headings", height=6)
            for chave, label in [("modo", "Modo"), ("politica", "Política")] + colunas:
                tabela.heading(chave, text=label)
                tabela.column(chave, width=125, anchor="center", minwidth=80)
            tabela.tag_configure("sync", background="#EEF2FF")
            tabela.tag_configure("sem-sync", background="#FFFBEB")
            tabela.pack(fill="x")
            self.tabelas.append((tabela, colunas))
        rodape = ttk.Frame(pagina)
        rodape.pack(fill="x", pady=(12, 0))
        ttk.Label(rodape, text="Médias das repetições concluídas. Demandas aleatórias independentes por caso.", style="Muted.TLabel").pack(side="left")
        self.exportar_btn = ttk.Button(rodape, text="Exportar CSV", command=self.exportar, state="disabled")
        self.exportar_btn.pack(side="right")
        self.desenhar()
        root.after(100, self.processar)

    def iniciar(self):
        try:
            valores = [int(var.get()) for var in self.campos.values()]
            if min(valores) <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Configuração inválida", "Preencha todos os campos com números inteiros maiores que zero.", parent=self.root)
            return
        self.executando = True
        self.cancelar.clear()
        self.linhas = []
        self.resultados = {caso: [] for caso in motor.CASOS}
        self.progresso.configure(value=0, maximum=valores[3])
        self.iniciar_btn.configure(state="disabled")
        self.parar_btn.configure(state="normal")
        self.exportar_btn.configure(state="disabled")
        for entrada in self.entradas:
            entrada.configure(state="disabled")
        self.atualizar()
        self.status.set(f"Executando repetição 1/{valores[3]} · previsão mínima: {valores[2] * valores[3]} s")
        threading.Thread(target=self.executar, args=tuple(valores), daemon=True).start()

    def executar(self, bebes, cuidadoras, tempo, repeticoes):
        try:
            for repeticao in range(1, repeticoes + 1):
                if self.cancelar.is_set():
                    break
                resultados = motor.executar_repeticao(bebes, cuidadoras, tempo)
                self.eventos.put(("resultado", (repeticao, resultados, bebes, cuidadoras, tempo, repeticoes)))
            self.eventos.put(("fim", None))
        except Exception as erro:
            self.eventos.put(("erro", str(erro)))

    def processar(self):
        try:
            while True:
                tipo, dados = self.eventos.get_nowait()
                if tipo == "resultado":
                    rep, resultados, bebes, cuidadoras, tempo, total = dados
                    for (politica, modo), metricas in resultados.items():
                        self.resultados[(politica, modo)].append(metricas)
                        self.linhas.append(dict(cenario="Personalizado", bebes=bebes, cuidadoras=cuidadoras, tempo=tempo, repeticao=rep, politica=politica, modo=modo, **metricas))
                    self.progresso.configure(value=rep)
                    self.atualizar()
                    self.status.set("Finalizando…" if rep == total else f"Executando repetição {rep + 1}/{total} · resultados parciais disponíveis")
                    if self.cancelar.is_set():
                        self.status.set("Finalizando a comparação…")
                else:
                    self.executando = False
                    self.iniciar_btn.configure(state="normal")
                    self.parar_btn.configure(state="disabled")
                    for entrada in self.entradas:
                        entrada.configure(state="normal")
                    if tipo == "erro":
                        self.status.set("A execução falhou. Resultados já concluídos foram preservados.")
                        messagebox.showerror("Erro na comparação", dados, parent=self.root)
                    else:
                        self.status.set("Comparação interrompida. Resultados concluídos preservados." if self.cancelar.is_set() else "Comparação concluída. Explore as métricas ou exporte os resultados.")
        except queue.Empty:
            pass
        self.root.after(100, self.processar)

    def atualizar(self):
        reps = len(next(iter(self.resultados.values())))
        self.cards[0].configure(text=str(reps))
        for card, chave in zip(self.cards[1:], ("atendidos", "conflitos_fila")):
            valores = [motor.media_de(v, chave) for v in self.resultados.values() if v]
            card.configure(text=f"{sum(valores) / len(valores):.1f}" if valores else "—")
        for tabela, colunas in self.tabelas:
            tabela.delete(*tabela.get_children())
            for (politica, modo), execucoes in self.resultados.items():
                valores = ["Com sincronização" if modo == "sync" else "Sem sincronização", NOMES[politica]]
                for chave, _ in colunas:
                    valor = motor.media_de(execucoes, chave)
                    valores.append("—" if valor is None else (f"{valor:.0%}" if chave == "utilizacao" else f"{valor:.2f}"))
                tabela.insert("", "end", values=valores, tags=(modo,))
        self.exportar_btn.configure(state="normal" if self.linhas else "disabled")
        self.desenhar()

    def desenhar(self):
        cv = self.canvas
        cv.delete("all")
        largura, altura = max(cv.winfo_width(), 600), max(cv.winfo_height(), 220)
        chave, descricao = METRICAS[self.metrica.get()]
        self.nota.set(descricao)
        for x, modo, label in ((24, "sync", "Com sincronização"), (205, "sem-sync", "Sem sincronização")):
            cv.create_rectangle(x, 17, x + 10, 27, fill=CORES[modo], outline="")
            cv.create_text(x + 17, 22, text=label, anchor="w", fill=SUAVE, font=("Segoe UI", 10))
        if not self.linhas:
            cv.create_text(largura / 2, altura / 2, text="Os resultados aparecerão aqui após a primeira repetição", fill=SUAVE, font=("Segoe UI", 12))
            return
        valores = {caso: motor.media_de(execs, chave) for caso, execs in self.resultados.items()}
        escala = max(max(valores.values()) * 1.2, 1)
        base, topo, esquerda, direita = altura - 35, 60, 65, largura - 30
        for i in range(5):
            valor = escala * i / 4
            y = base - (base - topo) * i / 4
            cv.create_line(esquerda, y, direita, y, fill="#E8ECF3")
            cv.create_text(esquerda - 10, y, text=f"{valor:.1f}", anchor="e", fill=SUAVE, font=("Segoe UI", 9))
        passo = (direita - esquerda) / 3
        barra = min(65, passo * .25)
        for i, politica in enumerate(motor.POLITICAS):
            centro = esquerda + passo * (i + .5)
            for j, modo in enumerate(("sync", "sem-sync")):
                valor = valores[(politica, modo)]
                x = centro + (j - 1) * (barra + 6) + 3
                y = base - valor / escala * (base - topo)
                cv.create_rectangle(x, y, x + barra, base, fill=CORES[modo], outline="")
                cv.create_text(x + barra / 2, y - 12, text=f"{valor:.2f}", fill=TEXTO, font=("Segoe UI", 10, "bold"))
            cv.create_text(centro, base + 20, text=NOMES[politica], fill=TEXTO, font=("Segoe UI", 10))

    def parar(self):
        self.cancelar.set()
        self.parar_btn.configure(state="disabled")
        self.status.set("Parada solicitada. A repetição atual será concluída para preservar os resultados.")

    def exportar(self):
        caminho = filedialog.asksaveasfilename(parent=self.root, title="Exportar resultados por execução", defaultextension=".csv", initialfile="comparacao_resultados.csv", filetypes=[("Arquivo CSV", "*.csv")])
        if caminho:
            try:
                with open(caminho, "w", newline="", encoding="utf-8-sig") as arquivo:
                    escritor = csv.DictWriter(arquivo, fieldnames=list(self.linhas[0]))
                    escritor.writeheader()
                    escritor.writerows(self.linhas)
            except OSError as erro:
                messagebox.showerror("Erro ao exportar", str(erro), parent=self.root)
            else:
                messagebox.showinfo("Exportação concluída", "Resultados salvos em CSV.", parent=self.root)

    def fechar(self):
        if self.executando:
            self.parar()
            self.status.set("Encerrando após a repetição atual…")
            self.root.after(200, self.aguardar_fechamento)
        else:
            self.root.destroy()

    def aguardar_fechamento(self):
        if self.executando:
            self.root.after(200, self.aguardar_fechamento)
        else:
            self.root.destroy()


if __name__ == "__main__":
    ComparacaoApp(tk.Tk()).root.mainloop()
