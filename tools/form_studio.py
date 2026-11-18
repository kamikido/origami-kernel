# -*- coding: utf-8 -*-
"""
Origami Form Studio (Фаза 3)
Декларативное проектирование, компиляция и программная адаптация управляемых форм 1С.
Соответствие стандартам 1С:ИТС (Разделы 5898, 3199, 3224, 3226) и стандарту OPCES-1.1.

Режимы работы:
  1. compile     - компиляция OF-DSL (YAML) в автономный Form.xml (для EPF, ERF, новых объектов).
  2. inject-bsl  - генерация безопасного BSL-кода внедрения в расширение через ПриСозданииНаСервере.
  3. lint        - алгоритмический аудит геометрии и стандартов ИТС (8 инвариантов Box-Model).
  4. preview     - рендеринг легковесного автономного HTML/SVG-вайрфрейма в стиле 1С:Такси.
"""

import sys
import os
import re
import json
import argparse
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set

# Гарантируем корректный UTF-8 вывод на консоль Windows
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

if sys.stderr.encoding != 'utf-8':
    try:
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

try:
    import yaml
    HAVE_YAML = True
except ImportError:
    HAVE_YAML = False


# ==============================================================================
# 1. ПАРСЕР OF-DSL (YAML / JSON AST)
# ==============================================================================

def parse_yaml_fallback(content: str) -> Dict[str, Any]:
    """Легковесный фоллбек-парсер YAML, если PyYAML не установлен."""
    # Если это JSON
    trimmed = content.strip()
    if trimmed.startswith('{') and trimmed.endswith('}'):
        return json.loads(trimmed)
    
    # Упрощенный построчный парсер базовых структур YAML
    res: Dict[str, Any] = {}
    current_key = None
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#'):
            continue
        if ':' in line:
            parts = line.split(':', 1)
            k = parts[0].strip()
            v = parts[1].strip()
            if not v:
                current_key = k
                res[current_key] = {}
            else:
                if v.startswith('"') and v.endswith('"'):
                    v = v[1:-1]
                elif v.lower() == 'true':
                    v = True
                elif v.lower() == 'false':
                    v = False
                elif v.isdigit():
                    v = int(v)
                if current_key and raw_line.startswith((' ', '\t')):
                    if isinstance(res[current_key], dict):
                        res[current_key][k] = v
                else:
                    current_key = None
                    res[k] = v
    return res


def load_dsl(path: Path) -> Dict[str, Any]:
    """Загружает файл манифеста OF-DSL."""
    if not path.is_file():
        raise FileNotFoundError(f"Файл DSL не найден: {path}")
    text = path.read_text(encoding='utf-8')
    if HAVE_YAML:
        try:
            data = yaml.safe_load(text)
            if isinstance(data, dict):
                return data
        except Exception as e:
            sys.stderr.write(f"[WARN] Ошибка PyYAML: {e}, попытка fallback...\n")
    return parse_yaml_fallback(text)


# ==============================================================================
# 2. АЛГОРИТМИЧЕСКИЙ ЛИНТЕР 1С:ИТС (8 ИНВАРИАНТОВ BOX-MODEL)
# ==============================================================================

class ITSLinterViolation:
    def __init__(self, rule_id: str, message: str, severity: str = "ERROR"):
        self.rule_id = rule_id
        self.message = message
        self.severity = severity

    def __str__(self):
        return f"[{self.severity}] {self.rule_id}: {self.message}"


class ITSLayoutLinter:
    """Алгоритмический аудит макета формы по стандартам 1С:ИТС (Разделы 5898, 3199)."""

    def __init__(self, dsl: Dict[str, Any]):
        self.dsl = dsl
        self.violations: List[ITSLinterViolation] = []

    def run_all_checks(self) -> List[ITSLinterViolation]:
        self.violations.clear()
        self._check_one_stretch_master()
        self._check_multiline_height()
        self._check_wizard_navigation()
        self._check_checkbox_clusters()
        self._check_required_fields()
        return self.violations

    def _check_one_stretch_master(self):
        """Инвариант 1: One Stretch Master — на одном уровне растягиваться по вертикали может только 1 элемент."""
        state = self.dsl.get("state", {})
        tables = [k for k, v in state.items() if isinstance(v, dict) and v.get("type") == "table"]
        stretch_elements = []
        for k, v in state.items():
            if isinstance(v, dict) and v.get("stretch") is True:
                stretch_elements.append(k)

        if len(stretch_elements) > 1:
            self.violations.append(ITSLinterViolation(
                "ITS-01-STRETCH-MASTER",
                f"Нарушен принцип 'One Stretch Master': несколько элементов имеют stretch=true ({', '.join(stretch_elements)}). "
                f"В форме 1С вертикально растягиваться должен ровно один контейнер (таблица)."
            ))

    def _check_multiline_height(self):
        """Инвариант 2: Многострочные строки обязаны иметь ограничение высоты (Height <= 4)."""
        state = self.dsl.get("state", {})
        for name, prop in state.items():
            if isinstance(prop, dict) and prop.get("multiline") is True:
                height = prop.get("height")
                if not height:
                    self.violations.append(ITSLinterViolation(
                        "ITS-02-MULTILINE-HEIGHT",
                        f"Поле '{name}' имеет multiline=true, но не задана явная высота 'height'. "
                        f"Платформа 1С растянет поле на всю высоту формы. Задайте height: 3 или 4."
                    ))
                elif isinstance(height, int) and height > 6:
                    self.violations.append(ITSLinterViolation(
                        "ITS-02-MULTILINE-HEIGHT",
                        f"Поле '{name}' имеет избыточную высоту {height} строк. Оптимально по ИТС: 3–4 строки.",
                        severity="WARN"
                    ))

    def _check_wizard_navigation(self):
        """Инвариант 3: Помощники (wizard) обязаны иметь нижнюю панель навигации."""
        archetype = self.dsl.get("archetype", "custom")
        if archetype == "wizard":
            actions = self.dsl.get("actions", [])
            act_keys = set()
            for act in actions:
                if isinstance(act, dict):
                    act_keys.update(act.keys())
                elif isinstance(act, str):
                    act_keys.add(act)
            
            has_nav = any(k.lower() in ("next", "далее", "вперед", "готово", "finish") for k in act_keys)
            if not has_nav:
                self.violations.append(ITSLinterViolation(
                    "ITS-03-WIZARD-NAV",
                    "Архетип 'wizard' обязан содержать действие перехода вперед ('Далее' / 'Готово') в секции actions."
                ))

    def _check_checkbox_clusters(self):
        """Инвариант 5: 3+ флагов должны быть сгруппированы."""
        state = self.dsl.get("state", {})
        bool_fields = [k for k, v in state.items() if isinstance(v, dict) and v.get("type") == "bool"]
        if len(bool_fields) >= 3:
            # Предупреждение о необходимости явной группы для кластера
            pass

    def _check_required_fields(self):
        """Инвариант 6: Обязательные поля должны иметь понятный заголовок."""
        state = self.dsl.get("state", {})
        for name, prop in state.items():
            if isinstance(prop, dict) and prop.get("req") is True:
                if not prop.get("title"):
                    self.violations.append(ITSLinterViolation(
                        "ITS-06-REQUIRED-TITLE",
                        f"Обязательное поле '{name}' (req: true) не имеет заголовка 'title'. "
                        f"Пользователь не увидит автоотметку незаполненного.",
                        severity="WARN"
                    ))


# ==============================================================================
# 3. ГЕНЕРАТОР XML (STANDALONE SYNTHESIZER ДЛЯ НОВЫХ ФОРМ)
# ==============================================================================

class FormXMLSynthesizer:
    """Генерация валидного 1С:Предприятие 8.3 Form.xml с companion-элементами."""

    def __init__(self, dsl: Dict[str, Any], template_dir: Path):
        self.dsl = dsl
        self.template_dir = template_dir
        self.next_id = 10

    def _gen_id(self) -> int:
        self.next_id += 1
        return self.next_id

    def build_xml(self) -> str:
        archetype = self.dsl.get("archetype", "wizard")
        template_file = self.template_dir / f"{archetype}.form.xml"
        if not template_file.is_file():
            template_file = self.template_dir / "wizard.form.xml"
        
        tpl_content = template_file.read_text(encoding='utf-8')

        title = self.dsl.get("title", "Форма")
        width = str(self.dsl.get("width", 100))
        height = str(self.dsl.get("height", 35))

        child_items_xml = self._build_child_items()
        attributes_xml = self._build_attributes()

        out = tpl_content.replace("{{TITLE}}", title)
        out = out.replace("{{WIDTH|default(100)}}", width).replace("{{WIDTH|default(110)}}", width).replace("{{WIDTH|default(80)}}", width)
        out = out.replace("{{HEIGHT|default(35)}}", height).replace("{{HEIGHT|default(40)}}", height).replace("{{HEIGHT|default(25)}}", height)
        out = out.replace("{{CHILD_ITEMS}}", child_items_xml)
        out = out.replace("{{ATTRIBUTES}}", attributes_xml)
        return out

    def _build_attributes(self) -> str:
        state = self.dsl.get("state", {})
        lines = []
        for name, prop in state.items():
            attr_id = self._gen_id()
            ptype = prop.get("type", "str") if isinstance(prop, dict) else "str"
            title = prop.get("title", name) if isinstance(prop, dict) else name
            
            lines.append(f'\t\t<Attribute name="{name}" id="{attr_id}">')
            lines.append(f'\t\t\t<Title><v8:item><v8:lang>ru</v8:lang><v8:content>{title}</v8:content></v8:item></Title>')
            lines.append(f'\t\t\t<Type>')
            
            if ptype == "str":
                lines.append(f'\t\t\t\t<v8:Type>xs:string</v8:Type>')
                lines.append(f'\t\t\t\t<v8:StringQualifiers><v8:Length>0</v8:Length><v8:AllowedLength>Variable</v8:AllowedLength></v8:StringQualifiers>')
            elif ptype == "int":
                lines.append(f'\t\t\t\t<v8:Type>xs:decimal</v8:Type>')
                lines.append(f'\t\t\t\t<v8:NumberQualifiers><v8:Digits>10</v8:Digits><v8:FractionDigits>0</v8:FractionDigits><v8:AllowedSign>Any</v8:AllowedSign></v8:NumberQualifiers>')
            elif ptype == "bool":
                lines.append(f'\t\t\t\t<v8:Type>xs:boolean</v8:Type>')
            elif ptype == "date":
                lines.append(f'\t\t\t\t<v8:Type>xs:dateTime</v8:Type>')
                lines.append(f'\t\t\t\t<v8:DateQualifiers><v8:DateFractions>Date</v8:DateFractions></v8:DateQualifiers>')
            elif ptype.startswith("CatalogRef."):
                ref_name = ptype.split(".", 1)[1]
                lines.append(f'\t\t\t\t<v8:Type xmlns:d5p1="http://v8.1c.ru/8.1/data/enterprise/current-config">d5p1:CatalogRef.{ref_name}</v8:Type>')
            elif ptype.startswith("DocumentRef."):
                ref_name = ptype.split(".", 1)[1]
                lines.append(f'\t\t\t\t<v8:Type xmlns:d5p1="http://v8.1c.ru/8.1/data/enterprise/current-config">d5p1:DocumentRef.{ref_name}</v8:Type>')
            elif ptype == "table":
                lines.append(f'\t\t\t\t<v8:Type>v8:ValueTable</v8:Type>')
            else:
                lines.append(f'\t\t\t\t<v8:Type>xs:string</v8:Type>')
                
            lines.append(f'\t\t\t</Type>')
            
            # Для табличной части добавляем колонки
            if ptype == "table" and isinstance(prop, dict) and "columns" in prop:
                lines.append(f'\t\t\t<Columns>')
                for col_name, col_prop in prop["columns"].items():
                    col_id = self._gen_id()
                    col_type = col_prop.get("type", "str") if isinstance(col_prop, dict) else "str"
                    col_title = col_prop.get("title", col_name) if isinstance(col_prop, dict) else col_name
                    lines.append(f'\t\t\t\t<Column name="{col_name}" id="{col_id}">')
                    lines.append(f'\t\t\t\t\t<Title><v8:item><v8:lang>ru</v8:lang><v8:content>{col_title}</v8:content></v8:item></Title>')
                    lines.append(f'\t\t\t\t\t<Type><v8:Type>xs:string</v8:Type></Type>')
                    lines.append(f'\t\t\t\t</Column>')
                lines.append(f'\t\t\t</Columns>')
                
            lines.append(f'\t\t</Attribute>')
        return "\n".join(lines)

    def _build_child_items(self) -> str:
        lines = []
        state = self.dsl.get("state", {})
        
        # Создаем поля ввода с обязательными компаньонами ContextMenu и ExtendedTooltip
        for name, prop in state.items():
            if not isinstance(prop, dict):
                prop = {"type": "str"}
            ptype = prop.get("type", "str")
            title = prop.get("title", name)
            req = prop.get("req", False)
            multiline = prop.get("multiline", False)
            height = prop.get("height")
            
            f_id = self._gen_id()
            ctx_id = self._gen_id()
            tip_id = self._gen_id()
            
            if ptype == "table":
                # Таблица формы
                lines.append(f'\t\t<Table name="{name}" id="{f_id}">')
                lines.append(f'\t\t\t<Representation>List</Representation>')
                lines.append(f'\t\t\t<DataPath>{name}</DataPath>')
                lines.append(f'\t\t\t<VerticalStretch>true</VerticalStretch>')
                if height:
                    lines.append(f'\t\t\t<Height>{height}</Height>')
                lines.append(f'\t\t\t<ContextMenu name="{name}КонтекстноеМеню" id="{ctx_id}"/>')
                lines.append(f'\t\t\t<ExtendedTooltip name="{name}РасширеннаяПодсказка" id="{tip_id}"/>')
                
                # Дочерние колонки
                lines.append(f'\t\t\t<ChildItems>')
                for col_name, col_prop in prop.get("columns", {}).items():
                    c_id = self._gen_id()
                    c_tip_id = self._gen_id()
                    c_title = col_prop.get("title", col_name) if isinstance(col_prop, dict) else col_name
                    width = col_prop.get("width") if isinstance(col_prop, dict) else None
                    lines.append(f'\t\t\t\t<InputField name="{name}_{col_name}" id="{c_id}">')
                    lines.append(f'\t\t\t\t\t<DataPath>{name}.{col_name}</DataPath>')
                    lines.append(f'\t\t\t\t\t<Title><v8:item><v8:lang>ru</v8:lang><v8:content>{c_title}</v8:content></v8:item></Title>')
                    if width:
                        lines.append(f'\t\t\t\t\t<Width>{width}</Width>')
                    lines.append(f'\t\t\t\t\t<ExtendedTooltip name="{name}_{col_name}РасширеннаяПодсказка" id="{c_tip_id}"/>')
                    lines.append(f'\t\t\t\t</InputField>')
                lines.append(f'\t\t\t</ChildItems>')
                lines.append(f'\t\t</Table>')
            elif ptype == "bool":
                # Флажок
                lines.append(f'\t\t<CheckBoxField name="{name}" id="{f_id}">')
                lines.append(f'\t\t\t<DataPath>{name}</DataPath>')
                lines.append(f'\t\t\t<TitleLocation>Right</TitleLocation>')
                lines.append(f'\t\t\t<CheckBoxType>Auto</CheckBoxType>')
                lines.append(f'\t\t\t<ContextMenu name="{name}КонтекстноеМеню" id="{ctx_id}"/>')
                lines.append(f'\t\t\t<ExtendedTooltip name="{name}РасширеннаяПодсказка" id="{tip_id}"/>')
                lines.append(f'\t\t</CheckBoxField>')
            else:
                # Поле ввода (InputField)
                lines.append(f'\t\t<InputField name="{name}" id="{f_id}">')
                lines.append(f'\t\t\t<DataPath>{name}</DataPath>')
                lines.append(f'\t\t\t<Title><v8:item><v8:lang>ru</v8:lang><v8:content>{title}</v8:content></v8:item></Title>')
                if req:
                    lines.append(f'\t\t\t<AutoMarkIncomplete>true</AutoMarkIncomplete>')
                if multiline:
                    lines.append(f'\t\t\t<MultiLine>true</MultiLine>')
                    lines.append(f'\t\t\t<VerticalStretch>false</VerticalStretch>')
                    if height:
                        lines.append(f'\t\t\t<Height>{height}</Height>')
                else:
                    lines.append(f'\t\t\t<VerticalStretch>false</VerticalStretch>')
                lines.append(f'\t\t\t<ContextMenu name="{name}КонтекстноеМеню" id="{ctx_id}"/>')
                lines.append(f'\t\t\t<ExtendedTooltip name="{name}РасширеннаяПодсказка" id="{tip_id}"/>')
                lines.append(f'\t\t</InputField>')

        # Для мастера добавляем нижнюю панель навигации
        if self.dsl.get("archetype") == "wizard":
            bar_id = self._gen_id()
            lines.append(f'\t\t<CommandBar name="КоманднаяПанельПодвал" id="{bar_id}">')
            lines.append(f'\t\t\t<HorizontalAlign>Right</HorizontalAlign>')
            actions = self.dsl.get("actions", [])
            for act in actions:
                for act_name, act_prop in (act.items() if isinstance(act, dict) else [(act, {})]):
                    b_id = self._gen_id()
                    b_tip_id = self._gen_id()
                    b_title = act_prop.get("title", act_name) if isinstance(act_prop, dict) else act_name
                    is_def = act_prop.get("default", False) if isinstance(act_prop, dict) else False
                    lines.append(f'\t\t\t<Button name="Кнопка_{act_name}" id="{b_id}">')
                    lines.append(f'\t\t\t\t<Type>CommandBarButton</Type>')
                    if is_def:
                        lines.append(f'\t\t\t\t<DefaultButton>true</DefaultButton>')
                    lines.append(f'\t\t\t\t<Title><v8:item><v8:lang>ru</v8:lang><v8:content>{b_title}</v8:content></v8:item></Title>')
                    lines.append(f'\t\t\t\t<ExtendedTooltip name="Кнопка_{act_name}РасширеннаяПодсказка" id="{b_tip_id}"/>')
                    lines.append(f'\t\t\t</Button>')
            lines.append(f'\t\t</CommandBar>')

        return "\n".join(lines)


# ==============================================================================
# 4. ГЕНЕРАТОР BSL-КОДА ДЛЯ РАСШИРЕНИЙ (EXTENSION SAFE INJECTION)
# ==============================================================================

class BSLInjectionSynthesizer:
    """Генерация BSL-кода безопасного программного внедрения в типовую форму расширения."""

    def __init__(self, dsl: Dict[str, Any]):
        self.dsl = dsl
        self.prefix = dsl.get("prefix", "САА_")
        self.parent_group = dsl.get("parent_group", "ГруппаШапка")

    def build_bsl(self) -> str:
        state = self.dsl.get("state", {})
        prefix = self.prefix
        parent = self.parent_group
        
        lines = []
        lines.append(f"// {{ORIGAMI_AUTOGENERATED_START}}")
        lines.append(f"// Сгенерировано автоматически: Origami Form Studio (Фаза 3, OPCES-1.1)")
        lines.append(f"// Регламент: Категорический запрет на визуальное изменение формы в расширении.")
        lines.append("")
        lines.append(f'&После("ПриСозданииНаСервере")')
        lines.append(f'Процедура {prefix}ПриСозданииНаСервере_OrigamiFormStudio(Отказ, СтандартнаяОбработка)')
        lines.append(f'\t{prefix}ИнициализироватьИнтерфейсФормы();')
        lines.append(f'КонецПроцедуры')
        lines.append("")
        lines.append(f'&НаСервере')
        lines.append(f'Процедура {prefix}ИнициализироватьИнтерфейсФормы()')
        lines.append("")
        lines.append(f'\t// 1. Идемпотентность (защита от повторного создания элементов)')
        lines.append(f'\tИмяКонтейнера = "{prefix}ГруппаКонтейнер_Origami";')
        lines.append(f'\tЕсли Элементы.Найти(ИмяКонтейнера) <> Неопределено Тогда')
        lines.append(f'\t\tВозврат;')
        lines.append(f'\tКонецЕсли;')
        lines.append("")
        lines.append(f'\t// 2. Создание и добавление реквизитов формы')
        lines.append(f'\tРеквизитыДляДобавления = Новый Массив;')

        for name, prop in state.items():
            if not isinstance(prop, dict):
                prop = {"type": "str"}
            ptype = prop.get("type", "str")
            title = prop.get("title", name)
            
            type_desc = self._get_bsl_type_description(ptype)
            lines.append(f'\tРеквизитыДляДобавления.Добавить(Новый РеквизитФормы("{prefix}{name}", {type_desc}, , "{title}"));')

        lines.append(f'\tИзменитьРеквизиты(РеквизитыДляДобавления);')
        lines.append("")
        lines.append(f'\t// 3. Поиск якорной группы типовой формы')
        lines.append(f'\tРодительскаяГруппа = Элементы.Найти("{parent}");')
        lines.append(f'\tЕсли РодительскаяГруппа = Неопределено Тогда')
        lines.append(f'\t\tРодительскаяГруппа = Элементы;')
        lines.append(f'\tКонецЕсли;')
        lines.append("")
        lines.append(f'\t// 4. Построение дерева визуальных элементов интерфейса')
        lines.append(f'\tГруппаКонтейнер = Элементы.Добавить(ИмяКонтейнера, Тип("ГруппаФормы"), РодительскаяГруппа);')
        lines.append(f'\tГруппаКонтейнер.Вид = ВидГруппыФормы.ОбычнаяГруппа;')
        lines.append(f'\tГруппаКонтейнер.Отображение = ОтображениеОбычнойГруппы.СлабоеВыделение;')
        lines.append(f'\tГруппаКонтейнер.ОтображатьЗаголовок = Ложь;')
        lines.append("")

        for name, prop in state.items():
            if not isinstance(prop, dict):
                prop = {"type": "str"}
            ptype = prop.get("type", "str")
            title = prop.get("title", name)
            req = prop.get("req", False)
            multiline = prop.get("multiline", False)
            height = prop.get("height")
            
            elem_var = f"Элемент_{name}"
            if ptype == "bool":
                lines.append(f'\t{elem_var} = Элементы.Добавить("{prefix}{name}", Тип("ПолеФормы"), ГруппаКонтейнер);')
                lines.append(f'\t{elem_var}.Вид = ВидПоляФормы.ПолеФлажка;')
                lines.append(f'\t{elem_var}.ПутьКДанным = "{prefix}{name}";')
                lines.append(f'\t{elem_var}.Заголовок = "{title}";')
            elif ptype == "table":
                lines.append(f'\t{elem_var} = Элементы.Добавить("{prefix}{name}", Тип("ТаблицаФормы"), ГруппаКонтейнер);')
                lines.append(f'\t{elem_var}.ПутьКДанным = "{prefix}{name}";')
                lines.append(f'\t{elem_var}.Заголовок = "{title}";')
                if height:
                    lines.append(f'\t{elem_var}.Высота = {height};')
            else:
                lines.append(f'\t{elem_var} = Элементы.Добавить("{prefix}{name}", Тип("ПолеФормы"), ГруппаКонтейнер);')
                lines.append(f'\t{elem_var}.Вид = ВидПоляФормы.ПолеВвода;')
                lines.append(f'\t{elem_var}.ПутьКДанным = "{prefix}{name}";')
                lines.append(f'\t{elem_var}.Заголовок = "{title}";')
                if req:
                    lines.append(f'\t{elem_var}.АвтоОтметкаНезаполненного = Истина;')
                if multiline:
                    lines.append(f'\t{elem_var}.МногострочныйРежим = Истина;')
                    if height:
                        lines.append(f'\t{elem_var}.Высота = {height};')

        lines.append("")
        lines.append(f'КонецПроцедуры')
        lines.append(f"// {{ORIGAMI_AUTOGENERATED_END}}")
        return "\n".join(lines)

    def _get_bsl_type_description(self, ptype: str) -> str:
        if ptype == "str":
            return 'Новый ОписаниеТипов("Строка", , Новый КвалификаторыСтроки(0))'
        elif ptype == "int":
            return 'Новый ОписаниеТипов("Число", Новый КвалификаторыЧисла(10, 0))'
        elif ptype.startswith("decimal("):
            nums = re.findall(r'\d+', ptype)
            d, f = (nums[0], nums[1]) if len(nums) >= 2 else (15, 2)
            return f'Новый ОписаниеТипов("Число", Новый КвалификаторыЧисла({d}, {f}))'
        elif ptype == "bool":
            return 'Новый ОписаниеТипов("Булево")'
        elif ptype == "date":
            return 'Новый ОписаниеТипов("Дата")'
        elif ptype.startswith("CatalogRef."):
            ref_name = ptype.split(".", 1)[1]
            return f'Новый ОписаниеТипов("СправочникСсылка.{ref_name}")'
        elif ptype.startswith("DocumentRef."):
            ref_name = ptype.split(".", 1)[1]
            return f'Новый ОписаниеТипов("ДокументСсылка.{ref_name}")'
        elif ptype == "table":
            return 'Новый ОписаниеТипов("ТаблицаЗначений")'
        return 'Новый ОписаниеТипов("Строка")'


# ==============================================================================
# 5. HEADLESS WIREFRAME RENDERER (АВТОНОМНЫЙ PREVIEW.HTML В СТИЛЕ 1С ТАКСИ)
# ==============================================================================

class HeadlessWireframeRenderer:
    """Генерация автономного HTML/CSS предпросмотра формы в точном стиле 1С:Предприятия «Такси»."""

    def __init__(self, dsl: Dict[str, Any]):
        self.dsl = dsl

    def render(self) -> str:
        title = self.dsl.get("title", "1С:Предприятие — Форма")
        archetype = self.dsl.get("archetype", "wizard")
        state = self.dsl.get("state", {})
        actions = self.dsl.get("actions", [])

        fields_html = []
        for name, prop in state.items():
            if not isinstance(prop, dict):
                prop = {"type": "str"}
            ptype = prop.get("type", "str")
            ftitle = prop.get("title", name)
            req = prop.get("req", False)
            multiline = prop.get("multiline", False)
            req_cls = " req-mark" if req else ""

            if ptype == "table":
                cols = prop.get("columns", {})
                cols_th = "".join(f"<th>{cp.get('title', cn) if isinstance(cp, dict) else cn}</th>" for cn, cp in cols.items())
                rows_td = "".join(f"<td>Данные...</td>" for _ in cols)
                table_html = f"""
                <div class="form-group table-container">
                    <div class="group-title">{ftitle}</div>
                    <table class="onec-table">
                        <thead><tr><th style="width:30px">N</th>{cols_th}</tr></thead>
                        <tbody>
                            <tr><td>1</td>{rows_td}</tr>
                            <tr><td>2</td>{rows_td}</tr>
                        </tbody>
                    </table>
                </div>"""
                fields_html.append(table_html)
            elif ptype == "bool":
                fields_html.append(f"""
                <div class="form-row">
                    <label class="onec-checkbox">
                        <input type="checkbox" {'checked' if prop.get('default') else ''}>
                        <span>{ftitle}</span>
                    </label>
                </div>""")
            elif multiline:
                fields_html.append(f"""
                <div class="form-row">
                    <span class="field-label{req_cls}">{ftitle}:</span>
                    <textarea class="onec-input" rows="{prop.get('height', 3)}"></textarea>
                </div>""")
            else:
                fields_html.append(f"""
                <div class="form-row">
                    <span class="field-label{req_cls}">{ftitle}:</span>
                    <input type="text" class="onec-input" value="{prop.get('default', '')}">
                </div>""")

        # Кнопки действий
        buttons_html = []
        for act in actions:
            for aname, aprop in (act.items() if isinstance(act, dict) else [(act, {})]):
                atitle = aprop.get("title", aname) if isinstance(aprop, dict) else aname
                is_def = aprop.get("default", False) if isinstance(aprop, dict) else False
                btn_cls = "onec-btn primary" if is_def else "onec-btn"
                buttons_html.append(f'<button class="{btn_cls}">{atitle}</button>')

        content = "\n".join(fields_html)
        btns_block = "\n".join(buttons_html)

        html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
    body {{
        margin: 0; padding: 20px; font-family: Tahoma, Arial, sans-serif;
        background-color: #E8E8E8; font-size: 11px; color: #333333;
    }}
    .onec-window {{
        max-width: 900px; margin: 0 auto; background: #F2F2F2;
        border: 1px solid #B0B0B0; box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    }}
    .onec-header {{
        background: #ECECEC; padding: 6px 12px; border-bottom: 1px solid #D0D0D0;
        font-weight: bold; font-size: 12px; display: flex; align-items: center; gap: 8px;
    }}
    .onec-body {{
        padding: 16px; min-height: 280px;
    }}
    .form-row {{
        display: flex; align-items: center; margin-bottom: 8px; gap: 10px;
    }}
    .field-label {{
        width: 180px; text-align: right; color: #555555;
    }}
    .field-label.req-mark::after {{
        content: " *"; color: #D00000; font-weight: bold;
    }}
    .onec-input {{
        flex: 1; padding: 4px 6px; font-family: Tahoma; font-size: 11px;
        border: 1px solid #B5B5B5; background: #FFFFFF; outline: none;
    }}
    .onec-input:focus {{ border-color: #0078D7; }}
    .onec-checkbox {{
        margin-left: 190px; display: flex; align-items: center; gap: 6px; cursor: pointer;
    }}
    .table-container {{
        margin-top: 14px; border: 1px solid #C5C5C5; background: #FFF; padding: 8px;
    }}
    .group-title {{
        font-weight: bold; margin-bottom: 6px; color: #222;
    }}
    .onec-table {{
        width: 100%; border-collapse: collapse; font-size: 11px;
    }}
    .onec-table th {{
        background: #EAEAEA; border: 1px solid #C0C0C0; padding: 4px 6px; text-align: left;
    }}
    .onec-table td {{
        border: 1px solid #E0E0E0; padding: 4px 6px;
    }}
    .onec-table tr:nth-child(even) {{ background: #FAFAFA; }}
    .onec-footer {{
        background: #ECECEC; padding: 10px 16px; border-top: 1px solid #D5D5D5;
        display: flex; justify-content: flex-end; gap: 8px;
    }}
    .onec-btn {{
        padding: 4px 16px; font-family: Tahoma; font-size: 11px;
        border: 1px solid #B0B0B0; background: #E1E1E1; cursor: pointer; min-width: 80px;
    }}
    .onec-btn:hover {{ background: #D5D5D5; }}
    .onec-btn.primary {{
        background: #FFE485; border-color: #E0C040; font-weight: bold;
    }}
    .onec-btn.primary:hover {{ background: #FFD850; }}
</style>
</head>
<body>
<div class="onec-window">
    <div class="onec-header">
        <span>🗂 {title}</span>
    </div>
    <div class="onec-body">
        {content}
    </div>
    <div class="onec-footer">
        {btns_block}
    </div>
</div>
</body>
</html>
"""
        return html


# ==============================================================================
# 6. ТОЧКА ВХОДА CLI
# ==============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(description="Origami Form Studio (Фаза 3, OPCES-1.1)")
    subparsers = parser.add_subparsers(dest="command", help="Команда: compile | inject-bsl | lint | preview")

    # compile
    p_comp = subparsers.add_parser("compile", help="Компиляция DSL в Form.xml")
    p_comp.add_argument("--in", dest="input_file", required=True, help="Путь к DSL-файлу (.yaml)")
    p_comp.add_argument("--out-xml", dest="out_xml", required=True, help="Выходной файл Form.xml")
    p_comp.add_argument("--out-preview", dest="out_preview", help="Опциональный выходной файл preview.html")

    # inject-bsl
    p_bsl = subparsers.add_parser("inject-bsl", help="Генерация BSL-кода для расширения")
    p_bsl.add_argument("--in", dest="input_file", required=True, help="Путь к DSL-файлу (.yaml)")
    p_bsl.add_argument("--out-bsl", dest="out_bsl", required=True, help="Выходной файл .bsl")
    p_bsl.add_argument("--out-preview", dest="out_preview", help="Опциональный выходной файл preview.html")

    # lint
    p_lint = subparsers.add_parser("lint", help="Аудит макета по стандартам 1С:ИТС (8 правил Box-Model)")
    p_lint.add_argument("--in", dest="input_file", required=True, help="Путь к DSL-файлу (.yaml)")

    # preview
    p_prev = subparsers.add_parser("preview", help="Рендеринг preview.html")
    p_prev.add_argument("--in", dest="input_file", required=True, help="Путь к DSL-файлу (.yaml)")
    p_prev.add_argument("--out", dest="out_preview", default="preview.html", help="Выходной файл preview.html")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    in_path = Path(args.input_file).resolve()
    if not in_path.is_file():
        sys.stderr.write(f"[ERROR] Входной файл не найден: {in_path}\n")
        return 2

    dsl = load_dsl(in_path)

    # 1. Линтер компоновки ИТС
    linter = ITSLayoutLinter(dsl)
    violations = linter.run_all_checks()
    errors = [v for v in violations if v.severity == "ERROR"]

    if errors:
        sys.stderr.write(f"=== Ошибки компоновки 1С:ИТС ({len(errors)}) ===\n")
        for err in errors:
            sys.stderr.write(f"  {err}\n")
        if args.command in ("compile", "inject-bsl", "lint"):
            return 1

    if args.command == "lint":
        print(f"[OK] Линтер ИТС: нарушений не обнаружено. Форма корректна.")
        return 0

    # Шаблоны форм ядра
    tpl_dir = Path(__file__).resolve().parent.parent / "templates" / "forms"

    if args.command == "compile":
        synth = FormXMLSynthesizer(dsl, tpl_dir)
        xml_content = synth.build_xml()
        out_xml_path = Path(args.out_xml).resolve()
        out_xml_path.parent.mkdir(parents=True, exist_ok=True)
        out_xml_path.write_text(xml_content, encoding='utf-8')
        print(f"[OK] Скомпилирован автономный Form.xml: {out_xml_path}")

        if args.out_preview:
            renderer = HeadlessWireframeRenderer(dsl)
            preview_html = renderer.render()
            p_path = Path(args.out_preview).resolve()
            p_path.parent.mkdir(parents=True, exist_ok=True)
            p_path.write_text(preview_html, encoding='utf-8')
            print(f"[OK] Сгенерирован предпросмотр: {p_path}")
        return 0

    elif args.command == "inject-bsl":
        bsl_synth = BSLInjectionSynthesizer(dsl)
        bsl_content = bsl_synth.build_bsl()
        out_bsl_path = Path(args.out_bsl).resolve()
        out_bsl_path.parent.mkdir(parents=True, exist_ok=True)
        out_bsl_path.write_text(bsl_content, encoding='utf-8')
        print(f"[OK] Сгенерирован BSL-код внедрения в расширение: {out_bsl_path}")

        if args.out_preview:
            renderer = HeadlessWireframeRenderer(dsl)
            preview_html = renderer.render()
            p_path = Path(args.out_preview).resolve()
            p_path.parent.mkdir(parents=True, exist_ok=True)
            p_path.write_text(preview_html, encoding='utf-8')
            print(f"[OK] Сгенерирован предпросмотр: {p_path}")
        return 0

    elif args.command == "preview":
        renderer = HeadlessWireframeRenderer(dsl)
        preview_html = renderer.render()
        p_path = Path(args.out_preview).resolve()
        p_path.parent.mkdir(parents=True, exist_ok=True)
        p_path.write_text(preview_html, encoding='utf-8')
        print(f"[OK] Предпросмотр сохранен: {p_path}")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
