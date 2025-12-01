import asyncio
import aiohttp
import time
import json
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, asdict
import logging
from pathlib import Path
import flet as ft

# Настройка логирования
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class VLESSConfig:
    """Конфигурация VLESS сервера"""
    server: str
    server_port: int
    uuid: str
    server_name: str = "vasya2.vaskeshu.ru"
    path: str = "/"
    speed_mbps: float = 0.0
    latency_ms: float = 0.0
    status: str = "unknown"
    tag: str = ""


class VLESSChecker:
    """Класс для проверки VLESS серверов"""

    def __init__(self, timeout: int = 10, test_size_mb: float = 1.0):
        self.timeout = timeout
        self.test_size_bytes = int(test_size_mb * 1024 * 1024)
        self.test_url = "https://speed.cloudflare.com/__down?bytes=1048576"

    async def check_latency(self, host: str, port: int) -> Tuple[bool, float]:
        """Проверка латентности до сервера"""
        try:
            start_time = time.time()
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=self.timeout
            )
            latency = (time.time() - start_time) * 1000
            writer.close()
            await writer.wait_closed()
            return True, latency
        except Exception as e:
            logger.debug(f"Latency check failed for {host}:{port} - {e}")
            return False, 0.0

    async def measure_speed(self, config: VLESSConfig, progress_callback=None) -> VLESSConfig:
        """Измерение скорости через прокси"""
        try:
            if progress_callback:
                progress_callback(
                    f"Проверка {config.server}:{config.server_port}...")

            is_reachable, latency = await self.check_latency(config.server, config.server_port)

            if not is_reachable:
                config.status = "unreachable"
                logger.warning(
                    f"❌ {config.server}:{config.server_port} - недоступен")
                return config

            config.latency_ms = latency

            connector = aiohttp.TCPConnector(ssl=False, force_close=True)
            timeout = aiohttp.ClientTimeout(total=self.timeout)

            async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                start_time = time.time()

                async with session.get(self.test_url) as response:
                    if response.status == 200:
                        data = await response.read()
                        elapsed_time = time.time() - start_time

                        bytes_received = len(data)
                        speed_mbps = (bytes_received /
                                      (1024 * 1024)) / elapsed_time

                        config.speed_mbps = round(speed_mbps, 2)
                        config.status = "ok"

                        logger.info(f"✅ {config.server}:{config.server_port} - "
                                    f"Скорость: {config.speed_mbps} MB/s, "
                                    f"Латентность: {config.latency_ms:.1f}ms")
                    else:
                        config.status = "error"

        except asyncio.TimeoutError:
            config.status = "timeout"
        except Exception as e:
            config.status = "error"
            logger.error(f"❌ {config.server}:{config.server_port} - {e}")

        return config

    async def check_servers(self, configs: List[VLESSConfig], progress_callback=None) -> List[VLESSConfig]:
        """Проверка списка серверов"""
        tasks = [self.measure_speed(config, progress_callback)
                 for config in configs]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        valid_results = [r for r in results if isinstance(r, VLESSConfig)]
        return valid_results


def filter_servers(results: List[VLESSConfig],
                   max_speed_mbps: Optional[float] = None,
                   min_speed_mbps: Optional[float] = None) -> List[VLESSConfig]:
    """Фильтрация серверов по скорости"""
    filtered = [r for r in results if r.status == "ok"]

    if max_speed_mbps is not None:
        filtered = [r for r in filtered if r.speed_mbps < max_speed_mbps]

    if min_speed_mbps is not None:
        filtered = [r for r in filtered if r.speed_mbps > min_speed_mbps]

    # Сортировка от БОЛЬШЕЙ скорости к МЕНЬШЕЙ
    filtered.sort(key=lambda x: x.speed_mbps, reverse=True)
    return filtered


def save_results(results: List[VLESSConfig], prefix: str = "vless_results"):
    """Сохранение результатов с сортировкой от большей скорости к меньшей"""
    # Сортируем от большей скорости к меньшей
    sorted_results = sorted(results, key=lambda x: x.speed_mbps, reverse=True)

    json_data = [asdict(r) for r in sorted_results]

    json_filename = f"{prefix}.json"
    with open(json_filename, 'w', encoding='utf-8') as f:
        json.dump(json_data, f, indent=2, ensure_ascii=False)

    txt_filename = f"{prefix}.txt"
    with open(txt_filename, 'w', encoding='utf-8') as f:
        f.write("VLESS Server Check Results (от большей скорости к меньшей)\n")
        f.write("=" * 80 + "\n\n")

        for i, r in enumerate(sorted_results, 1):
            f.write(f"#{i} Rank\n")
            f.write(f"Server: {r.server}:{r.server_port}\n")
            f.write(f"Tag: {r.tag}\n")
            f.write(f"Speed: {r.speed_mbps} MB/s ⭐\n")
            f.write(f"Latency: {r.latency_ms:.1f} ms\n")
            f.write(f"Status: {r.status}\n")
            f.write(f"UUID: {r.uuid}\n")
            f.write(f"SNI: {r.server_name}\n")
            f.write(f"Path: {r.path}\n")
            f.write("-" * 80 + "\n\n")

    return json_filename, txt_filename


class VLESSCheckerApp:
    def __init__(self, page: ft.Page):
        self.page = page
        self.page.title = "VLESS Server Checker"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.window_width = 1200
        self.page.window_height = 750
        self.page.padding = 0

        self.checker = None
        self.results = []

        # UI Components
        self.servers_input = ft.TextField(
            label="IP:Port список (один на строку)",
            multiline=True,
            min_lines=5,
            max_lines=10,
            hint_text="81.255.155.10:443\n192.243.113.108:443\n...",
        )

        self.uuid_input = ft.TextField(
            label="UUID",
            value="32a53867-a558-45a9-a73d-4844c375f0c8",
            width=400,
        )

        self.sni_input = ft.TextField(
            label="Server Name (SNI)",
            value="vasya2.vaskeshu.ru",
            width=400,
        )

        self.path_input = ft.TextField(
            label="WebSocket Path",
            value="/",
            width=200,
        )

        self.timeout_input = ft.TextField(
            label="Timeout (сек)",
            value="10",
            width=150,
            keyboard_type=ft.KeyboardType.NUMBER,
        )

        self.max_speed_input = ft.TextField(
            label="Макс. скорость (MB/s)",
            value="1.5",
            width=200,
            keyboard_type=ft.KeyboardType.NUMBER,
        )

        self.min_speed_input = ft.TextField(
            label="Мин. скорость (MB/s)",
            value="0",
            width=200,
            keyboard_type=ft.KeyboardType.NUMBER,
        )

        self.progress_bar = ft.ProgressBar(width=400, visible=False)
        self.status_text = ft.Text(
            "Готов к проверке", size=16, weight=ft.FontWeight.BOLD)

        self.results_list = ft.ListView(
            expand=True,
            spacing=10,
            padding=10,
        )

        self.check_btn = ft.ElevatedButton(
            "Начать проверку",
            icon=ft.Icons.PLAY_CIRCLE_OUTLINE,
            on_click=self.start_check,
            height=45,
            style=ft.ButtonStyle(
                color=ft.Colors.WHITE,
                bgcolor={
                    ft.ControlState.DEFAULT: ft.Colors.BLUE_700,
                    ft.ControlState.HOVERED: ft.Colors.BLUE_800,
                },
                shape=ft.RoundedRectangleBorder(radius=8),
            ),
        )

        self.save_all_btn = ft.ElevatedButton(
            "Сохранить все",
            icon=ft.Icons.SAVE_OUTLINED,
            on_click=self.save_all_results,
            disabled=True,
            height=40,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=8),
            ),
        )

        self.save_filtered_btn = ft.ElevatedButton(
            "Сохранить отфильтрованные",
            icon=ft.Icons.FILTER_LIST,
            on_click=self.save_filtered_results,
            disabled=True,
            height=40,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=8),
            ),
        )

        self.load_json_btn = ft.OutlinedButton(
            "Загрузить JSON",
            icon=ft.Icons.FILE_UPLOAD_OUTLINED,
            on_click=self.load_from_json,
            height=40,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=8),
            ),
        )

        self.load_txt_btn = ft.OutlinedButton(
            "Загрузить TXT",
            icon=ft.Icons.DESCRIPTION_OUTLINED,
            on_click=self.load_from_txt,
            height=40,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=8),
            ),
        )

        self.stats_text = ft.Text("", size=14, color=ft.Colors.BLUE_300)

        self.build_ui()

    def build_ui(self):
        """Построение интерфейса"""

        # Левая панель - настройки
        left_panel = ft.Container(
            content=ft.Column([
                ft.Container(
                    content=ft.Text(
                        "Настройки проверки",
                        size=22,
                        weight=ft.FontWeight.W_600,
                        color=ft.Colors.WHITE,
                    ),
                    margin=ft.margin.only(bottom=20),
                ),
                self.servers_input,
                ft.Container(height=10),
                self.uuid_input,
                ft.Container(height=10),
                self.sni_input,
                ft.Container(height=10),
                ft.Row([
                    self.path_input,
                    self.timeout_input,
                ], spacing=10),
                ft.Container(height=20),
                ft.Container(
                    content=ft.Text(
                        "Фильтры скорости",
                        size=16,
                        weight=ft.FontWeight.W_500,
                        color=ft.Colors.BLUE_200,
                    ),
                    margin=ft.margin.only(bottom=10),
                ),
                ft.Row([
                    self.min_speed_input,
                    self.max_speed_input,
                ], spacing=10),
                ft.Container(height=20),
                self.check_btn,
                ft.Container(height=15),
                ft.Row([
                    self.load_json_btn,
                    self.load_txt_btn,
                ], spacing=10),
                ft.Container(height=15),
                self.progress_bar,
                ft.Container(height=10),
                self.status_text,
            ], scroll=ft.ScrollMode.AUTO, spacing=0),
            width=450,
            padding=25,
            bgcolor=ft.Colors.GREY_900,
        )

        # Правая панель - результаты
        right_panel = ft.Container(
            content=ft.Column([
                ft.Container(
                    content=ft.Row([
                        ft.Text(
                            "Результаты проверки",
                            size=22,
                            weight=ft.FontWeight.W_600,
                            color=ft.Colors.WHITE,
                        ),
                        ft.Container(expand=True),
                        self.save_all_btn,
                        self.save_filtered_btn,
                    ], spacing=10),
                    margin=ft.margin.only(bottom=15),
                ),
                self.stats_text,
                ft.Container(height=10),
                ft.Container(
                    content=self.results_list,
                    expand=True,
                    bgcolor=ft.Colors.GREY_900,
                    border_radius=10,
                ),
            ], spacing=0),
            expand=True,
            padding=25,
        )

        # Главный контейнер
        self.page.add(
            ft.Row([
                left_panel,
                right_panel,
            ], expand=True, spacing=0)
        )

    def parse_servers(self, text: str) -> List[Tuple[str, int]]:
        """Парсинг списка серверов"""
        servers = []
        for line in text.strip().split('\n'):
            line = line.strip()
            if not line or ':' not in line:
                continue
            try:
                ip, port = line.split(':')
                servers.append((ip.strip(), int(port.strip())))
            except ValueError:
                continue
        return servers

    def update_status(self, message: str):
        """Обновление статуса"""
        self.status_text.value = message
        self.page.update()

    async def start_check(self, e):
        """Начать проверку"""
        servers = self.parse_servers(self.servers_input.value)

        if not servers:
            self.show_dialog(
                "Ошибка", "Введите хотя бы один сервер в формате IP:Port")
            return

        # Блокируем кнопку
        self.check_btn.disabled = True
        self.progress_bar.visible = True
        self.page.update()

        # Создаем конфигурации
        configs = []
        for i, (ip, port) in enumerate(servers):
            config = VLESSConfig(
                server=ip,
                server_port=port,
                uuid=self.uuid_input.value,
                server_name=self.sni_input.value,
                path=self.path_input.value,
                tag=f"Server-{i+1}"
            )
            configs.append(config)

        # Запускаем проверку
        timeout = int(self.timeout_input.value)
        self.checker = VLESSChecker(timeout=timeout)

        self.update_status(f"Проверка {len(configs)} серверов...")

        self.results = await self.checker.check_servers(configs, self.update_status)

        # Фильтруем результаты (только для отображения успешных с фильтром)
        max_speed = float(
            self.max_speed_input.value) if self.max_speed_input.value else None
        min_speed = float(
            self.min_speed_input.value) if self.min_speed_input.value else None

        # Для отображения показываем ВСЕ результаты, отсортированные по скорости
        # Сначала успешные (от быстрых к медленным), потом неуспешные
        successful = [r for r in self.results if r.status == "ok"]
        failed = [r for r in self.results if r.status != "ok"]

        successful.sort(key=lambda x: x.speed_mbps, reverse=True)
        all_sorted = successful + failed

        # Отфильтрованные для статистики
        filtered = filter_servers(self.results, max_speed, min_speed)

        # Отображаем ВСЕ результаты
        self.display_results(all_sorted)

        # Обновляем статистику
        ok_count = len([r for r in self.results if r.status == "ok"])
        filtered_count = len(filtered)

        if filtered:
            fastest = filtered[0]
            self.stats_text.value = (
                f"Всего: {len(self.results)} | "
                f"Успешных: {ok_count} | "
                f"Отфильтровано: {filtered_count} | "
                f"Самый быстрый: {fastest.speed_mbps} MB/s"
            )
        else:
            self.stats_text.value = (
                f"Всего: {len(self.results)} | "
                f"Успешных: {ok_count} | "
                f"Отфильтровано: {filtered_count}"
            )

        self.update_status(
            f"✅ Проверка завершена! Найдено {filtered_count} подходящих серверов")

        # Разблокируем кнопки
        self.check_btn.disabled = False
        self.progress_bar.visible = False
        self.save_all_btn.disabled = False
        self.save_filtered_btn.disabled = False
        self.page.update()

    def display_results(self, results: List[VLESSConfig]):
        """Отображение результатов"""
        self.results_list.controls.clear()

        if not results:
            self.results_list.controls.append(
                ft.Container(
                    content=ft.Column([
                        ft.Icon(ft.Icons.SEARCH_OFF, size=64,
                                color=ft.Colors.GREY_600),
                        ft.Text(
                            "Нет результатов",
                            size=18,
                            color=ft.Colors.GREY_500,
                            weight=ft.FontWeight.W_500,
                        ),
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10),
                    alignment=ft.alignment.center,
                    padding=50,
                )
            )
        else:
            for i, r in enumerate(results, 1):
                # Цвета и иконки в зависимости от статуса
                if r.status == "ok":
                    color = ft.Colors.GREEN_400
                    icon = ft.Icons.CHECK_CIRCLE_ROUNDED
                    status_text = "Работает"
                    bg_color = ft.Colors.with_opacity(0.1, ft.Colors.GREEN_400)
                elif r.status == "unreachable":
                    color = ft.Colors.RED_400
                    icon = ft.Icons.CANCEL_ROUNDED
                    status_text = "Недоступен"
                    bg_color = ft.Colors.with_opacity(0.1, ft.Colors.RED_400)
                elif r.status == "timeout":
                    color = ft.Colors.ORANGE_400
                    icon = ft.Icons.ACCESS_TIME_ROUNDED
                    status_text = "Таймаут"
                    bg_color = ft.Colors.with_opacity(
                        0.1, ft.Colors.ORANGE_400)
                else:  # error
                    color = ft.Colors.RED_300
                    icon = ft.Icons.WARNING_ROUNDED
                    status_text = "Ошибка"
                    bg_color = ft.Colors.with_opacity(0.1, ft.Colors.RED_300)

                # Бейдж для топ-3 успешных
                rank_badge = None
                if r.status == "ok" and i <= 3:
                    if i == 1:
                        rank_icon = ft.Icons.MILITARY_TECH_ROUNDED
                        rank_color = ft.Colors.AMBER_400
                    elif i == 2:
                        rank_icon = ft.Icons.WORKSPACE_PREMIUM_ROUNDED
                        rank_color = ft.Colors.GREY_400
                    else:  # 3
                        rank_icon = ft.Icons.STAR_ROUNDED
                        rank_color = ft.Colors.ORANGE_300

                    rank_badge = ft.Icon(rank_icon, size=24, color=rank_color)

                card = ft.Container(
                    content=ft.Row([
                        # Левая часть - статус иконка
                        ft.Container(
                            content=ft.Icon(icon, color=color, size=32),
                            padding=10,
                            border_radius=8,
                            bgcolor=bg_color,
                        ),
                        # Средняя часть - информация
                        ft.Container(
                            content=ft.Column([
                                ft.Row([
                                    ft.Text(
                                        f"#{i}",
                                        size=14,
                                        color=ft.Colors.GREY_500,
                                        weight=ft.FontWeight.W_600,
                                    ),
                                    ft.Text(
                                        f"{r.server}:{r.server_port}",
                                        size=16,
                                        weight=ft.FontWeight.W_600,
                                        color=ft.Colors.WHITE,
                                    ),
                                    rank_badge if rank_badge else ft.Container(),
                                ], spacing=8),
                                ft.Text(
                                    r.tag,
                                    size=12,
                                    color=ft.Colors.GREY_500,
                                ),
                            ], spacing=4),
                            expand=True,
                        ),
                        # Правая часть - метрики
                        ft.Container(
                            content=ft.Row([
                                # Скорость
                                ft.Container(
                                    content=ft.Column([
                                        ft.Row([
                                            ft.Icon(ft.Icons.SPEED, size=16,
                                                    color=ft.Colors.BLUE_300),
                                            ft.Text("Скорость", size=11,
                                                    color=ft.Colors.GREY_500),
                                        ], spacing=4),
                                        ft.Text(
                                            f"{r.speed_mbps} MB/s" if r.status == "ok" else "—",
                                            size=15,
                                            weight=ft.FontWeight.W_600,
                                            color=ft.Colors.BLUE_300,
                                        ),
                                    ], spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                                    padding=10,
                                    border_radius=8,
                                    bgcolor=ft.Colors.with_opacity(
                                        0.1, ft.Colors.BLUE_300),
                                ),
                                # Латентность
                                ft.Container(
                                    content=ft.Column([
                                        ft.Row([
                                            ft.Icon(
                                                ft.Icons.NETWORK_PING, size=16, color=ft.Colors.ORANGE_300),
                                            ft.Text("Пинг", size=11,
                                                    color=ft.Colors.GREY_500),
                                        ], spacing=4),
                                        ft.Text(
                                            f"{r.latency_ms:.0f} ms" if r.latency_ms > 0 else "—",
                                            size=15,
                                            weight=ft.FontWeight.W_600,
                                            color=ft.Colors.ORANGE_300,
                                        ),
                                    ], spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                                    padding=10,
                                    border_radius=8,
                                    bgcolor=ft.Colors.with_opacity(
                                        0.1, ft.Colors.ORANGE_300),
                                ),
                                # Статус
                                ft.Container(
                                    content=ft.Column([
                                        ft.Text("Статус", size=11,
                                                color=ft.Colors.GREY_500),
                                        ft.Text(
                                            status_text,
                                            size=15,
                                            weight=ft.FontWeight.W_600,
                                            color=color,
                                        ),
                                    ], spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                                    padding=10,
                                    border_radius=8,
                                ),
                            ], spacing=10),
                        ),
                    ], spacing=15),
                    padding=15,
                    border_radius=12,
                    bgcolor=ft.Colors.SURFACE,
                    border=ft.border.all(
                        1, ft.Colors.with_opacity(0.1, ft.Colors.WHITE)),
                )
                self.results_list.controls.append(card)

        self.page.update()

    def save_all_results(self, e):
        """Сохранить все результаты"""
        if not self.results:
            return

        json_file, txt_file = save_results(self.results, "all_vless_results")
        self.show_dialog(
            "Успех", f"Результаты сохранены (от быстрых к медленным):\n{json_file}\n{txt_file}")

    def save_filtered_results(self, e):
        """Сохранить отфильтрованные результаты"""
        if not self.results:
            return

        max_speed = float(
            self.max_speed_input.value) if self.max_speed_input.value else None
        min_speed = float(
            self.min_speed_input.value) if self.min_speed_input.value else None

        filtered = filter_servers(self.results, max_speed, min_speed)

        if not filtered:
            self.show_dialog("Предупреждение", "Нет серверов для сохранения")
            return

        json_file, txt_file = save_results(filtered, "filtered_vless_servers")
        self.show_dialog(
            "Успех", f"Отфильтрованные результаты сохранены (от быстрых к медленным):\n{json_file}\n{txt_file}")

    def load_from_json(self, e):
        """Загрузить конфигурацию из JSON"""
        file_picker = ft.FilePicker(on_result=self.on_json_file_picked)
        self.page.overlay.append(file_picker)
        self.page.update()
        file_picker.pick_files(allowed_extensions=["json"])

    def load_from_txt(self, e):
        """Загрузить серверы из текстового файла"""
        file_picker = ft.FilePicker(on_result=self.on_txt_file_picked)
        self.page.overlay.append(file_picker)
        self.page.update()
        file_picker.pick_files(allowed_extensions=["txt"])

    def on_json_file_picked(self, e: ft.FilePickerResultEvent):
        """Обработка выбранного JSON файла"""
        if not e.files:
            return

        try:
            file_path = e.files[0].path
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Загружаем данные
            if isinstance(data, dict) and 'outbounds' in data:
                # Формат из вашего JSON
                servers_text = []
                for outbound in data['outbounds']:
                    if outbound.get('type') == 'vless':
                        server = outbound.get('server', '')
                        port = outbound.get('server_port', '')
                        servers_text.append(f"{server}:{port}")

                self.servers_input.value = '\n'.join(servers_text)

                # Берем UUID и SNI из первого outbound
                if data['outbounds']:
                    first = data['outbounds'][0]
                    self.uuid_input.value = first.get('uuid', '')
                    if 'tls' in first:
                        self.sni_input.value = first['tls'].get(
                            'server_name', '')
                    if 'transport' in first:
                        self.path_input.value = first['transport'].get(
                            'path', '/')

                self.show_dialog(
                    "Успех", f"Загружено {len(servers_text)} серверов из JSON")

            self.page.update()

        except Exception as ex:
            self.show_dialog("Ошибка", f"Не удалось загрузить файл: {ex}")

    def on_txt_file_picked(self, e: ft.FilePickerResultEvent):
        """Обработка выбранного текстового файла"""
        if not e.files:
            return

        try:
            file_path = e.files[0].path
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Парсим серверы из файла
            servers = self.parse_servers(content)

            if servers:
                # Записываем серверы в поле ввода
                servers_text = [f"{ip}:{port}" for ip, port in servers]
                self.servers_input.value = '\n'.join(servers_text)

                self.show_dialog(
                    "Успех", f"Загружено {len(servers)} серверов из TXT файла")
            else:
                self.show_dialog(
                    "Предупреждение", "В файле не найдено серверов в формате IP:Port")

            self.page.update()

        except Exception as ex:
            self.show_dialog("Ошибка", f"Не удалось загрузить файл: {ex}")

    def show_dialog(self, title: str, message: str):
        """Показать диалоговое окно"""
        dialog = ft.AlertDialog(
            title=ft.Text(title),
            content=ft.Text(message),
            actions=[
                ft.TextButton(
                    "OK", on_click=lambda e: self.close_dialog(dialog))
            ],
        )
        self.page.dialog = dialog
        dialog.open = True
        self.page.update()

    def close_dialog(self, dialog):
        """Закрыть диалог"""
        dialog.open = False
        self.page.update()


def main(page: ft.Page):
    app = VLESSCheckerApp(page)


if __name__ == "__main__":
    ft.app(target=main)
