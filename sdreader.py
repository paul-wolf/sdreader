from dataclasses import dataclass, field
import os
import shutil
import subprocess
import tkinter as tk
from tkinter import ttk
from datetime import datetime
import threading
import signal
import itertools
from urllib.request import urlopen
import tkinter.messagebox as messagebox


def bytes_to_human_readable(num_bytes):
    """
    Convert bytes to a human-readable string (e.g., KB, MB, GB).
    """
    step_unit = 1024
    units = ["B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB"]

    for unit in units:
        if num_bytes < step_unit:
            return f"{num_bytes:.2f} {unit}"
        num_bytes /= step_unit

    return f"{num_bytes:.2f} YB"  # In case the number is extremely large


@dataclass
class Context:
    mount_point: str
    root: tk.Tk
    current_file_var: tk.StringVar
    base_destination: str
    gif_frames: list = field(default_factory=list)
    stop_animation: threading.Event = None


def plog(message):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")


def is_sd_card_mac(device):
    result = subprocess.run(["diskutil", "info", device], capture_output=True, text=True)
    for line in result.stdout.splitlines():
        if "Media Name" in line and "SD" in line:
            return True
    return False


def is_sd_card(device, mount_point):
    if os.name == "posix":
        if os.uname().sysname == "Darwin":
            return is_sd_card_mac(device)
        elif "mmcblk" in device or "sd" in device:
            return True
    elif os.name == "nt":
        result = subprocess.run(
            ["wmic", "logicaldisk", "where", f"DeviceID='{device}'", "get", "MediaType"],
            capture_output=True,
            text=True,
        )
        if "Removable Media" in result.stdout:
            return True
    return False


def read_mounts_mac():
    mounts = []
    result = subprocess.run(["mount"], capture_output=True, text=True)
    for line in result.stdout.splitlines():
        parts = line.split()
        device = parts[0]
        mount_point = parts[2]
        filesystem_type = parts[4].strip("()")
        options = parts[5].strip("()")
        mount_info = {
            "device": device,
            "mount_point": mount_point,
            "filesystem_type": filesystem_type,
            "options": options,
            "is_sd_card": is_sd_card(device, mount_point),
        }
        mounts.append(mount_info)
    return mounts


def read_mounts_linux():
    mounts = []
    with open("/proc/mounts", "r") as f:
        for line in f:
            parts = line.split()
            device = parts[0]
            mount_point = parts[1]
            mount_info = {
                "device": device,
                "mount_point": mount_point,
                "filesystem_type": parts[2],
                "options": parts[3],
                "dump": parts[4],
                "pass": parts[5],
                "is_sd_card": is_sd_card(device, mount_point),
            }
            mounts.append(mount_info)
    return mounts


def read_mounts_windows():
    mounts = []
    result = subprocess.run(
        ["wmic", "logicaldisk", "get", "DeviceID,FileSystem,Size,FreeSpace,VolumeName"],
        capture_output=True,
        text=True,
    )
    lines = result.stdout.splitlines()
    keys = [key.strip() for key in lines[0].split()]
    for line in lines[1:]:
        if line.strip():
            values = line.split()
            mount_info = dict(zip(keys, values))
            mount_info["is_sd_card"] = is_sd_card(mount_info["DeviceID"], None)
            mount_info["mount_point"] = mount_info["DeviceID"]
            mount_info["device"] = mount_info["DeviceID"].replace(":", "")
            mount_info["Size"] = bytes_to_human_readable(int(mount_info["Size"]))
            mounts.append(mount_info)
    return mounts


def get_mounts():
    if os.name == "posix":
        if os.uname().sysname == "Darwin":
            return read_mounts_mac()
        else:
            return read_mounts_linux()
    elif os.name == "nt":
        return read_mounts_windows()
    return []


def write_selected_mounts(selected_mounts, filename="selected_mounts.txt"):
    with open(filename, "w") as f:
        for mount in selected_mounts:
            f.write(f"{mount}\n")


def copy_sd_card_contents(ctx: Context):
    print(f"copy_sd_card_contents: {ctx.root=}")
    if not os.path.exists(ctx.base_destination):
        os.makedirs(ctx.base_destination)
    for root, dirs, files in os.walk(ctx.mount_point):
        relative_path = os.path.relpath(root, ctx.mount_point)
        dest_path = os.path.join(ctx.base_destination, relative_path)
        if not os.path.exists(dest_path):
            os.makedirs(dest_path)
        for file in files:
            src_file = os.path.join(root, file)
            dest_file = os.path.join(dest_path, file)
            try:
                shutil.copy2(src_file, dest_file)
                plog(f"Copied {src_file} to {dest_file}")
                ctx.current_file_var.set(f"Copying: {src_file}")
                ctx.root.update_idletasks()  # Refresh the UI

            except PermissionError:
                plog(f"Permission denied: {src_file}")
                continue


def format_sd_card(device):
    if os.name == "posix":
        if os.uname().sysname == "Darwin":
            # macOS: Use diskutil to erase the disk
            plog(f"Formatting {device} on macOS")
            subprocess.run(["diskutil", "eraseDisk", "JHFS+", "SDCard", device])
        else:
            # Linux: Use mkfs to format the disk
            plog(f"Formatting {device} on Linux")
            subprocess.run(["mkfs.ext4", device])
    elif os.name == "nt":
        # Windows: Use format command
        plog(f"Formatting {device} on Windows")
        subprocess.run(["format", device, "/FS:NTFS", "/P:1"], input=b"Y\n", text=True)


def copy_files(ctx: Context, selected_mounts: list):
    print(f"{ctx.root=}")
    for i, mount_point in enumerate(selected_mounts):
        mount_name = os.path.basename(mount_point.strip("/"))
        ctx.base_destination = os.path.join(ctx.base_destination, f"{mount_name}_{i}")
        ctx.mount_point = mount_point
        # print(ctx)
        # raise SystemExit
        copy_sd_card_contents(ctx)
    ctx.activity_label.config(image="")
    ctx.stop_animation.set()
    ctx.current_file_var.set("Done copying !")
    ctx.root.update_idletasks()


def get_gif_frames():
    gif_url = "https://media.giphy.com/media/3oEjI6SIIHBdRxXI40/giphy.gif"
    response = urlopen(gif_url)
    gif_data = response.read()
    gif_image = tk.PhotoImage(data=gif_data)
    gif_frames = []
    try:
        while True:
            gif_frames.append(gif_image.copy())
            gif_image.tk.call(gif_image, "configure", "-format", f"gif -index {len(gif_frames)}")
    except tk.TclError:
        pass
    return gif_frames


def create_gui(mounts, base_destination):
    root = tk.Tk()
    root.geometry("800x600")

    root.title("Select Mount Points")
    current_file_var = tk.StringVar(value="No file being copied")
    current_file_label = ttk.Label(root, textvariable=current_file_var)
    current_file_label.grid(row=3, column=0, columnspan=2, sticky=tk.W, padx=10, pady=10)
    current_file_var.set("Ready to copy files")
    selected_mounts = []

    activity_label = ttk.Label(root)
    activity_label.grid(row=1, column=1, sticky=tk.W, padx=10, pady=10)
    stop_animation = threading.Event()

    gif_frames = get_gif_frames()

    destination_label = ttk.Label(root, text="Destination Directory:")
    destination_label.grid(row=0, column=0, sticky=tk.W, padx=10, pady=10)

    destination_var = tk.StringVar(value=base_destination)
    destination_entry = ttk.Entry(root, textvariable=destination_var, width=50)
    destination_entry.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=10, pady=10)

    ctx = Context(
        mount_point=None,
        root=root,
        current_file_var=current_file_var,
        base_destination=base_destination,
        gif_frames=gif_frames,
        stop_animation=stop_animation,
    )

    def animate_gif(stop_animation):
        for frame in itertools.cycle(ctx.gif_frames):
            if stop_animation.is_set():
                break
            ctx.activity_label.config(image=frame)
            ctx.root.update_idletasks()
            ctx.root.after(100)

    def on_select():
        ctx.base_destination = destination_var.get()
        selected_mounts.clear()
        for var, mount in zip(checkbox_vars, mounts):
            if var.get():
                selected_mounts.append(mount["mount_point"])
        # print(selected_mounts)
        if selected_mounts:
            
            os.makedirs(ctx.base_destination, exist_ok=True)
            threading.Thread(target=animate_gif).start()
            threading.Thread(
                target=copy_files,
                args=(ctx, selected_mounts),
            ).start()

    def on_format():
        selected_mounts.clear()
        for var, mount in zip(checkbox_vars, mounts):
            if var.get():
                selected_mounts.append(mount["device"])

        if not selected_mounts:
            messagebox.showwarning("No Selection", "No mounts selected for formatting.")
            return

        confirm = messagebox.askyesno(
            "Confirm Format", "This will forever delete all data from the selected mounts. Continue?"
        )
        if confirm:
            root.quit()
            for device in selected_mounts:
                format_sd_card(device)

    # frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S))

    frame = ttk.Frame(root, padding="10")
    frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

    checkbox_vars = []
    for mount in mounts:
        var = tk.BooleanVar()
        checkbox = ttk.Checkbutton(
            frame, text=f"{mount['mount_point']} ({mount.get('VolumeName')}, {mount.get('Size')})", variable=var
        )
        checkbox.grid(sticky=tk.W)
        checkbox_vars.append(var)

    button_save = ttk.Button(frame, text="Start copying", command=on_select)
    button_save.grid(sticky=tk.W)

    button_format = ttk.Button(frame, text="Format Mounts", command=on_format)
    button_format.grid(sticky=tk.W)

    # Center the window on the screen
    root.update_idletasks()
    window_width = root.winfo_width()
    window_height = root.winfo_height()
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    position_top = int(screen_height / 2 - window_height / 2)
    position_right = int(screen_width / 2 - window_width / 2)
    root.geometry(f"{window_width}x{window_height}+{position_right}+{position_top}")

    def signal_handler(sig, frame):
        print("Exiting gracefully...")
        root.quit()
        exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    root.mainloop()


def signal_handler(sig, frame):
    print("Exiting gracefully...")
    exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    mounts = get_mounts()
    # mounts = [m for m in mounts if "/Volumes" in m["mount_point"] and "/System/Volumes" not in m["mount_point"]]
    # print(mounts)
    mounts = [m for m in mounts if m["device"] != "C"]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_destination = f"./data-{timestamp}"
    create_gui(mounts, base_destination)
