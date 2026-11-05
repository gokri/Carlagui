import tkinter as tk
from tkinter import ttk, messagebox


class CarlaGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Carla Simulator GUI")
        self.root.geometry("800x600")
        self._build_ui()

    def _build_ui(self):
        # Header
        header = tk.Label(self.root, text="CARLA Simulator Control Panel",
                          font=("Helvetica", 18, "bold"), pady=10)
        header.pack()

        # Connection frame
        conn_frame = ttk.LabelFrame(self.root, text="Connection", padding=10)
        conn_frame.pack(fill="x", padx=20, pady=5)

        tk.Label(conn_frame, text="Host:").grid(row=0, column=0, sticky="w")
        self.host_var = tk.StringVar(value="localhost")
        tk.Entry(conn_frame, textvariable=self.host_var, width=20).grid(row=0, column=1, padx=5)

        tk.Label(conn_frame, text="Port:").grid(row=0, column=2, sticky="w")
        self.port_var = tk.StringVar(value="2000")
        tk.Entry(conn_frame, textvariable=self.port_var, width=8).grid(row=0, column=3, padx=5)

        tk.Button(conn_frame, text="Connect", command=self._connect).grid(row=0, column=4, padx=10)

        # Status bar
        self.status_var = tk.StringVar(value="Status: Disconnected")
        status_bar = tk.Label(self.root, textvariable=self.status_var,
                              bd=1, relief="sunken", anchor="w")
        status_bar.pack(side="bottom", fill="x")

        # Main area placeholder
        main_frame = ttk.LabelFrame(self.root, text="Simulation View", padding=10)
        main_frame.pack(fill="both", expand=True, padx=20, pady=10)
        tk.Label(main_frame, text="Connect to CARLA server to begin.",
                 foreground="gray").pack(expand=True)

    def _connect(self):
        host = self.host_var.get()
        port = self.port_var.get()
        # Placeholder — replace with actual carla.Client(host, int(port)) call
        self.status_var.set(f"Status: Connecting to {host}:{port}...")
        messagebox.showinfo("Connect", f"Attempting connection to {host}:{port}\n"
                                       "(Install the CARLA Python API to enable real connection)")
        self.status_var.set(f"Status: Connected to {host}:{port}")


def main():
    root = tk.Tk()
    CarlaGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
