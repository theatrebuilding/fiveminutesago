import psutil

# Kill any processes using ports 7701, 7702, 8801, 7799 and 8802 before proceeding
def kill_existing_connections():
    ports = [7701, 7702, 8801, 8802, 7799]
    for port in ports:
        for conn in psutil.net_connections(kind='inet'):
            if conn.laddr.port == port:
                pid = conn.pid
                if pid:
                    print(f"🛑 Killing process {pid} using port {port}")
                    proc = psutil.Process(pid)
                    proc.terminate()
                    proc.wait()

def main():
    kill_existing_connections()

if __name__ == "__main__":
    main()
