import threading
from queue import Queue, Full, Empty
import asyncio
import ctypes
import threading
import time
from queue import Queue, Full, Empty

import bettercam
import pyautogui
import pygetwindow

from gui.hub import Hub
from gui.login import login
from gui.main import App
from gui.select_brawler import SelectBrawler
from lobby_automation import LobbyAutomation
from play import Play
from stage_manager import StageManager
from state_finder.main import get_state
from time_management import TimeManagement
from utils import ScreenshotTaker, load_toml_as_dict, current_wall_model_is_latest, api_base_url
from utils import get_brawler_list, update_missing_brawler_ranges, update_icons, check_version, async_notify_user, \
    update_wall_model_classes, get_latest_wall_model_file, get_latest_version

pyla_version = load_toml_as_dict("./cfg/general_config.toml")['pyla_version']
chosen_monitor = int(load_toml_as_dict("./cfg/general_config.toml")['monitor'])
camera = bettercam.create(device_idx=chosen_monitor)
frame_lock = threading.Lock()
frame_available = threading.Event()
Screenshot = ScreenshotTaker(camera)
frame_queue = Queue(maxsize=1)
debug = load_toml_as_dict("cfg/general_config.toml")['super_debug'] == "yes"


def capture_loop():
    while True:
        image = Screenshot.take()
        try:
            frame_queue.put(image, block=False)
        except Full:
            try:
                frame_queue.get_nowait()
            except Empty:
                pass
            frame_queue.put(image, block=False)


capture_thread = threading.Thread(target=capture_loop, daemon=True)


def pyla_main(data):
    class Main:

        def __init__(self, lobby_automator):
            self.specific_brawlers_data = []
            self.Play = Play(*self.load_models())
            self.Time_management = TimeManagement()
            self.lobby_automator = lobby_automator
            self.Stage_manager = StageManager(Screenshot, data, frame_queue)
            self.states_requiring_data = ["play_store", "brawl_stars_crashed", "lobby"]
            if data[0]['automatically_pick']:
                if debug: print("Picking brawler automatically")
                self.lobby_automator.select_brawler(data[0]['brawler'])
            self.Play.current_brawler = data[0]['brawler']
            self.no_detections_action_threshold = 60 * 8
            self.initialize_stage_manager()
            self.state = None
            try:
                self.max_ips = int(load_toml_as_dict("cfg/general_config.toml")['max_ips'])
            except ValueError:
                self.max_ips = None

        def initialize_stage_manager(self):
            self.Stage_manager.Trophy_observer.win_streak = 0
            self.Stage_manager.Trophy_observer.current_trophies = data[0]['trophies']
            self.Stage_manager.Trophy_observer.current_mastery = data[0]['mastery'] if data[0][
                                                                                           'mastery'] != "" else -99999

        @staticmethod
        def load_models():
            folder_path = "./models/"
            model_names = ['mainInGameModel.onnx', 'brawlersInGame.onnx', 'startingScreenModel.onnx',
                           'tileDetector.onnx']
            loaded_models = []

            for name in model_names:
                loaded_models.append(folder_path + name)
            return loaded_models

        def restart_brawl_stars(self):
            loop = asyncio.new_event_loop()
            loop.run_until_complete(async_notify_user("bot_is_stuck"))
            print("\nBot got stuck. Webhook sent. Pausing...")
            loop.close()
            input("Bot is paused. Press Enter to unpause and continue...")
            print("Resuming bot...\n")

        def manage_time_tasks(self, frame):
            if self.Time_management.state_check():
                state = get_state(frame)
                self.state = state
                frame_data = frame if state in self.states_requiring_data else None
                self.Stage_manager.do_state(state, frame_data)

            if self.Time_management.no_detections_check():
                frame_data = self.Play.time_since_detections
                print(self.Play.time_since_detections)
                for key, value in frame_data.items():
                    if time.time() - value > self.no_detections_action_threshold:
                        self.restart_brawl_stars()

            if self.Time_management.idle_check():
                print("check for idle!")
                self.lobby_automator.check_for_idle(frame)

        def main(self):
            s_time = time.time()
            c = 0
            while True:
                # Reset counter and time every second
                if abs(s_time - time.time()) > 1:
                    print(c, "IPS")
                    s_time = time.time()
                    c = 0

                try:
                    frame = frame_queue.get(timeout=1)
                except Empty:
                    continue

                self.manage_time_tasks(frame)  # Replace with your actual method

                if self.Time_management.specific_brawlers_check():
                    self.Play.get_specific_data(frame)
                    self.Time_management.states['game_start'] = time.time()

                brawler = self.Stage_manager.brawlers_pick_data[0]['brawler']
                self.Play.main(frame, brawler, self.state)
                c += 1

                # Enforce max IPS if set
                if self.max_ips:
                    time_per_frame = 1 / self.max_ips
                    elapsed_time = time.time() - s_time
                    if elapsed_time < time_per_frame:
                        time.sleep(time_per_frame - elapsed_time)

    try:
        window = pygetwindow.getWindowsWithTitle('LDPlayer')[0]

        if window.isMinimized:
            window.restore()

        try:
            window.activate()
        except:
            pass

        window.maximize()
    except:
        print(
            "Couldn't find LDPlayer window. Using another emulator isn't recommended and can lead to unexpected issues.")

    main = Main(
        lobby_automator=LobbyAutomation(camera, frame_queue)
    )
    main.main()
    return width, height


width, height = pyautogui.size()
if width > 1920:
    print(
        "⚠️Warning:⚠️ Screen resolution is higher 1920x1080. This might cause major issues. Please lower your resolution to 1920x1080 in computer settings (Display Settings), NOT LDPlayer settings. ⚠️⚠️⚠️")

orig_screen_width, orig_screen_height = 1920, 1080
width_ratio = width / orig_screen_width
height_ratio = height / orig_screen_height

all_brawlers = get_brawler_list()
if api_base_url != "localhost":
    update_missing_brawler_ranges(all_brawlers)
    update_icons()
    check_version()
    update_wall_model_classes()
    if not current_wall_model_is_latest():
        print(
            "New Wall detection model found, downloading... (this might take a few minutes depending on your internet speed)")
        get_latest_wall_model_file()

user32 = ctypes.windll.user32
user32.SetProcessDPIAware()  # Makes sure the process is DPI aware
dpi_scale = int(user32.GetDpiForSystem())
if dpi_scale != 96:
    print(
        "⚠️⚠️⚠️ Warning ⚠️⚠️⚠️\nScreen's zoom isn't 100%. \nPlease change your Zoom to 100% in your windows settings (just above the display resolution). \nOtherwise there will be unexpected problems (don't hesitate to ask for support in the discord server.")

# Use the smaller ratio to maintain aspect ratio
scale_factor = min(width_ratio, height_ratio)
app = App(login, SelectBrawler, pyla_main, all_brawlers, Hub)
app.start(capture_thread, pyla_version, get_latest_version)
