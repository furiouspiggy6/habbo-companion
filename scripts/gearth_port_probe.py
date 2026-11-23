#!/usr/bin/env python3
"""Windows CI probe: can Java bind G-Earth's Flash socket beside Python's relay?"""
import socket
import subprocess
import tempfile
from pathlib import Path
from shutil import which

def main():
    sock=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
    sock.bind(("127.0.0.3",0))
    port=sock.getsockname()[1]
    sock.listen(1)
    print(f"Companion upstream bind 127.0.0.3:{port}=OK",flush=True)
    other=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    try:
        other.bind(("127.0.0.2",port))
        other.listen(1)
        print(f"Parallel Python downstream bind 127.0.0.2:{port}=OK",flush=True)
    except OSError as exc:
        print(f"Parallel Python downstream bind FAILED: {exc!r}",flush=True)
    finally:
        other.close()
    java=which("java")
    if java is not None:
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/"GearthPortProbe.java"
            source.write_text("""import java.net.*;
public class GearthPortProbe {
  public static void main(String[] args) throws Exception {
    int port=Integer.parseInt(args[0]);
    try(ServerSocket server=new ServerSocket(port,10,InetAddress.getByName("127.0.0.2"))){
      System.out.println("Parallel Java ServerSocket 127.0.0.2:"+port+"=OK");
    } catch (Exception e) {
      System.out.println("Parallel Java ServerSocket FAILED: "+e);
    }
  }
}
""",encoding="utf-8")
            result=subprocess.run([java,str(source),str(port)],text=True,
                 capture_output=True,timeout=35,check=False)
            print("Java test code="+str(result.returncode),flush=True)
            print(result.stdout[:800]+result.stderr[:800],flush=True)
    else:
        print("Java unavailable on runner",flush=True)
    sock.close()

if __name__=="__main__":
    main()
