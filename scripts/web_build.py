#!/usr/bin/env python3

''' Web Build

by Will Griffin (whgriff05)

Based on yasb.py by Peter Bui (pnutzh4x0r)

-----

Project Structure:
    pages/                 # Pages described in YAML with HTML and MD
    public/                # Location for built HTML files
    scripts/               # Scripts for building site
    static/                # Static information: CSS, images, etc
    templates/             # Base HTML files

'''

from dataclasses import dataclass
import datetime
from functools import cache
import itertools
import os
import re
import shutil
import sys

from typing import Callable, Iterator, Optional

import dateutil.parser
import jinja2
import markdown
import markdown.extensions.codehilite
import yaml

from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, MofNCompleteColumn

@dataclass
class Page:
    # User Defined Fields
    title:      str             # Page Title
    internal:   dict            # Internally defined data
    external:   dict            # Externally defined data
    body:       str             # Page Body
    date:       str             # Page Date
    extensions: list[str]       # List of extensions

    # Generated Fields
    path:       list[str]       # Page path (list of directories)
    sources:    list[str]       # Page sources
    link:       str             # Page Link

    navigation: Optional[list[dict[str, str]]]=None

    # Class Variables
    Template ='''{{% extends "base.html" %}}
{{% block main %}}
{}
{{% endblock main %}}'''

    # Methods
    @staticmethod
    def load(path: str) -> 'Page':
        # Load data from YAML file
        with open(path) as stream:
            data = yaml.safe_load(stream)

        # Store path
        data["sources"] = [path]

        # Ensure internal data exists
        if not "internal" in data:
            data["internal"] = {}

        # Ensure page date exists
        if not "date" in data:
            timestamp = get_timestamp(path)
            data["date"] = datetime.datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")

        # Store path as components
        data["path"] = re.findall(r'pages/(.*)', path)[0].split("/")

        # Add extensions
        data["extensions"] = Site.DEFAULT_EXTENSIONS + [
                Site.Extensions.get(e, e) for e in data.get("extensions", [])
                ]

        # Generate page link
        data["link"] = os.path.join(*data["path"]).replace(".yaml", ".html")

        return Page(**data)

    def build(self, site: "Site"):
        body = markdown.markdown(self.body, extensions=self.extensions)
        template = site.environment.from_string(Page.Template.format(body))
        settings = {
                "site": site,
                "page": self,
                "dateutil": dateutil,
                "itertools": itertools,
                }

        return template.render(**settings)

@dataclass
class Site:
    # User Defined Fields
    title:      str                 # Site Title
    navigation: Optional[list[dict[str, str]]]=None
    prefix:     Optional[str]=None  # Site Prefix

    # Generated Fields
    path:       str=os.curdir       # Path to pages

    # Internal Fields
    _environment: Optional[jinja2.Environment]=None
    _pages: Optional[list[str]]=None
    _templates: Optional[list[str]]=None
    _panel: Optional[Panel]=None
    _progress: Optional[Progress]=None

    # Class Variables
    Extensions = {
            'codehilite': markdown.extensions.codehilite.CodeHiliteExtension(noclasses=False) 
            }

    Filters = []

    # Constants
    DEFAULT_EXTENSIONS = [
            'abbr',
            'def_list',
            'fenced_code',
            'footnotes',
            'md_in_html',
            'tables',
            Extensions['codehilite'],
            ]

    # Decorator
    @staticmethod
    def filter(func):
        Site.Filters.append(func)
        return func

    # Properties
    @property
    def pages_path(self):
        return os.path.join(self.path, "pages")

    @property
    def templates_path(self):
        return os.path.join(self.path, "templates")

    @property
    def public_path(self):
        return os.path.join(self.path, "public")

    @property
    def static_path(self):
        return os.path.join(self.path, "static")

    @property
    def environment(self):
        if not self._environment is None:
            return self._environment

        self._environment = jinja2.Environment(
                loader = jinja2.FileSystemLoader(self.templates_path),
                trim_blocks = True,
                )

        for filter_function in self.Filters:
            self._environment.filters[filter_function.__name__] = filter_function

        return self._environment

    @property
    def pages(self):
        if not self._pages is None:
            return self._pages

        self._pages = []
        file_paths = list(search_files(self.pages_path, lambda page: page.endswith(".yaml")))
        page_task = self.progress.add_task("[yellow]Loading", total=len(file_paths))

        for file_path in file_paths:
            file_name = file_path.replace(self.pages_path, '')[1:]
            description = f"[yellow]Loading[/yellow]   {file_name}"
            self.progress.console.print(description)

            self._pages.append(Page.load(file_path))

            self.progress.update(page_task, description=description, advance=1)

        return self._pages

    @property
    def templates(self):
        if not self._templates is None:
            return self._templates

        self._templates = [
                os.path.join(self.templates_path, t)
                for t in self.environment.list_templates()
                if t.endswith(".html")
                ]

        return self._templates

    @property
    def panel(self):
        if self._panel is None:
            self._panel = Panel(self.progress, title="web_build", border_style="blue")
        return self._panel

    @property
    def progress(self):
        if self._progress is None:
            self._progress = Progress(
                    "{task.description}",
                    SpinnerColumn(),
                    BarColumn(),
                    TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                    MofNCompleteColumn(),
                    )

        return self._progress
    
    @staticmethod
    def load(path):
        with open(path) as stream:
            data = yaml.safe_load(stream)

        return Site(**data)

    def build(self):
        if not os.path.exists(self.public_path):
            os.makedirs(self.public_path)

        templates_timestamp = max(get_timestamp(t) for t in self.templates)

        with Live(self.panel, refresh_per_second=10):
            page_task = self.progress.add_task('[green]Building', total=len(self.pages))

            for page in self.pages:
                target_path = os.path.join(self.public_path, *page.path).replace(".yaml", ".html")
                target_dir = os.path.dirname(target_path)
                target_name = target_path.replace(self.public_path, "")[1:]
                description = f"[green]Building[/green]   {target_name}"

                sources_timestamp = max(get_timestamp(s) for s in page.sources)
                target_timestamp = get_timestamp(target_path)

                if sources_timestamp > target_timestamp or templates_timestamp > target_timestamp:
                    self.progress.console.print(description)

                    if not os.path.exists(target_dir):
                        os.makedirs(target_dir)

                    with open(target_path, "w") as stream:
                        stream.write(page.build(self))

                self.progress.update(page_task, description=description, advance=1)

            static_paths = list(search_files(self.static_path, lambda page: not page.endswith(".swp")))
            static_task = self.progress.add_task("[cyan]Copying", total=len(static_paths))

            for static_path in static_paths:
                target_path = os.path.join(self.public_path, static_path)
                target_dir = os.path.dirname(target_path)
                target_name = os.path.normpath(target_path.replace(self.public_path, "")[1:])
                description = f"[cyan]Copying[/cyan]   {target_name}"

                if not os.path.exists(target_dir):
                    os.makedirs(target_dir)

                target_timestamp = get_timestamp(target_path)
                if get_timestamp(static_path) > target_timestamp:
                    self.progress.console.print(description)
                    shutil.copyfile(static_path, target_path)
                
                self.progress.update(static_task, description=description, advance=1)

# Functions
@Site.filter
def build_link(path: list[str]) -> str:
    return os.path.join(*path).replace(".yaml", ".html")

@Site.filter
def embed_icon(icon: str) -> str:
    with open(f"static/ico/{icon}.svg") as stream:
        return stream.read()

@cache
def get_timestamp(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except FileNotFoundError:
        return 0

def search_files(path: str, filter_func: Optional[Callable]=None) -> Iterator[str]:
    for root, _, files in os.walk(path):
        for file_name in files:
            file_path = os.path.join(root, file_name)
            if not filter_func or filter_func(file_path):
                yield file_path

# Main Function
def main():
    site_path = "site.yaml"
    if len(sys.argv) == 2:
        site_path = sys.argv[1]

    try:
        site = Site.load(site_path)
    except IOError:
        print(f"Unable to load {site_path}")
        sys.exit(1)

    site.build()

if __name__ == "__main__":
    main()





    
