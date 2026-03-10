#!/usr/bin/env python3

''' SWYG - Static Website YAML Generator

by Will Griffin (whgriff05)

inspired by yasb.py by Peter Bui (pnutzh4x0r)

-----

Project Structure:
    pages/              # Pages described in YAML
    public/             # Location for built HTML files
    scripts/            # Scripts for building site
    static/             # Static information: CSS, images, etc.
    templates/          # Base HTML files

'''

from dataclasses import dataclass
import datetime
import os
import re
import shutil
import sys

from typing import Callable, Iterator, Optional

import jinja2
import markdown
import markdown.extensions.codehilite
import markdown.extensions.toc
import yaml

from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, MofNCompleteColumn

@dataclass
class Page:
    # User Defined Fields
    title:      str                     # Page Title
    body:       str                     # Page Body
    date:       str                     # Page Date
    extensions: list[str]               # List of extensions

    # Generated Fields
    path:       list[str]               # Page Path (list of directories)
    sources:    list[str]               # Page sources
    link:       str                     # Page Link

    navigation: Optional[list[dict[str, str]]]=None

    # Class Variables
    Template = '''{{% extends "base.html" %}}
{{% block main %}}
{}
{{% endblock main %}}'''
    
    # Methods
    @staticmethod
    def load(path: str) -> 'Page':
        # Load YAML data
        with open(path) as stream:
            data = yaml.safe_load(stream)

        # Store path
        data["sources"] = [path]

        # Store date
        if not data.get("date"):
            timestamp = get_timestamp(path)
            data["date"] = datetime.datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")

        # Store directory list as path
        data["path"] = re.findall(r'pages/(.*)', path)[0].split("/")

        # Add extensions
        data["extensions"] = Site.DEFAULT_EXTENSIONS + [Site.Extensions.get(e, e) for e in data.get("extensions", [])]

        # Generate page link
        data["link"] = os.path.join(*data["path"]).replace(".yaml", ".html")

        return Page(**data)

    def build(self, site: "Site"):
        # Parse markdown body
        body = markdown.markdown(self.body, extensions=self.extensions)

        # Load template from source string
        template = site.environment.from_string(Page.Template.format(body))
        
        # Define settings
        settings = {
                "site": site,
                "page": self,
                }

        # Return jinja2 rendered page
        return template.render(**settings)

@dataclass
class Site:
    # User Defined Fields
    title:      str                 # Site Title
    navigation: Optional[list[dict[str, str]]]
    prefix:     Optional[str]=None  # Site Prefix

    # Generated Fields
    path:       str=os.curdir       # Path to pages/

    # Internal Fields
    _environment: Optional[jinja2.Environment]=None
    _pages: Optional[list["Page"]]=None        # List of paths to pages
    _templates: Optional[list[str]]=None    # List of paths to templates
    _panel: Optional[Panel]=None
    _progress: Optional[Progress]=None

    # Class Variables
    Extensions = {
            "codehilite": markdown.extensions.codehilite.CodeHiliteExtension(noclasses=False),
            "toc": markdown.extensions.toc.TocExtension(permalink=" #"),
            }

    Filters = []

    # Constants
    DEFAULT_EXTENSIONS = [
            "abbr",
            "def_list",
            "fenced_code",
            "footnotes",
            "md_in_html",
            "tables",
            Extensions["codehilite"],
            Extensions["toc"],
            ]

    # Decorator
    @staticmethod
    def filter(func):
        Site.Filters.append(func)
        return func

    # Path Properties
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

    # Environment Property
    @property
    def environment(self):
        # Looks for an already existing environment
        if not self._environment is None:
            return self._environment

        # Otherwise create a new environment
        self._environment = jinja2.Environment(
                loader = jinja2.FileSystemLoader(self.templates_path),
                trim_blocks = True,
                )

        # Add filter functions to the environment
        for filter_function in self.Filters:
            self._environment.filters[filter_function.__name__] = filter_function

        return self._environment

    # Page Property
    @property
    def pages(self):
        # Looks for an already existing list of pages
        if not self._pages is None:
            return self._pages

        # Otherwise get the list of pages
        self._pages = []
        
        # Gets list of page file paths
        file_paths = list(search_files(self.pages_path, lambda page: page.endswith(".yaml")))

        # Sets up the progress task
        page_task = self.progress.add_task("[yellow]Loading", total=len(file_paths))

        # For each file path, get the name, update the progress, and load the page
        for file_path in file_paths:
            # Get the name
            file_name = file_path.replace(self.pages_path, "")[1:]

            # Print the progress description
            description = f"[yellow]Loading[/yellow]   {file_name}"
            self.progress.console.print(description)

            # Load the page
            self._pages.append(Page.load(file_path))

            # Update the progress meter
            self.progress.update(page_task, description=description, advance=1)

        return self._pages

    # Templates Property
    @property
    def templates(self):
        if not self._templates is None:
            return self._templates

        self._templates = []

        for template in self.environment.list_templates():
            if template.endswith(".html"):
                template_path = os.path.join(self.templates_path, template)
                self._templates.append(template_path)

        return self._templates

    # Progress Panel Property
    @property
    def panel(self):
        if self._panel is None:
            self._panel = Panel(self.progress, title="SWYG - Static Website YAML Generator", border_style="rgb(202,231,151)")
        return self._panel

    # Progress Property
    @property
    def progress(self):
        # If no progress already exists
        if self._progress is None:
            # Create new progress
            self._progress = Progress(
                    "{task.description}",
                    SpinnerColumn(),
                    BarColumn(),
                    TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                    MofNCompleteColumn(),
                    )

        # Return the progress
        return self._progress

    # Methods
    @staticmethod
    def load(path):
        with open(path) as stream:
            # Open site yaml file
            data = yaml.safe_load(stream)

            # Unpack it to Site object
            return Site(**data)

    def build(self):
        # Make sure public directory path exists
        if not os.path.exists(self.public_path):
            os.makedirs(self.public_path)

        # Get timestamp for templates
        templates_ts = max(get_timestamp(t) for t in self.templates)

        # Set up progress Live context
        with Live(self.panel, refresh_per_second=10):
            # Building Pages

            # Set up page progress task
            page_task = self.progress.add_task("[green]Building", total=len(self.pages))

            for page in self.pages:
                # Define the target path, directory, and name
                target_path = os.path.join(self.public_path, *page.path).replace(".yaml", ".html")
                target_dir = os.path.dirname(target_path)
                target_name = target_path.replace(self.public_path, "")[1:]

                # Create description for progress
                description = f"[green]Building[/green]   {target_name}"
        
                # Get timestamps for the sources and target
                source_ts = max(get_timestamp(s) for s in page.sources)
                target_ts = get_timestamp(target_path)

                # If a page was modified after last build, rebuild the page
                if source_ts > target_ts or templates_ts > target_ts:
                    # Print the progress description
                    self.progress.console.print(description)

                    # Check for target directory existence
                    if not os.path.exists(target_dir):
                        os.makedirs(target_dir)

                    with open(target_path, "w") as stream:
                        # Build page to file
                        stream.write(page.build(self))

                # Update the progress meter
                self.progress.update(page_task, description=description, advance=1)

            # Copying Static Files

            # Get a list of static file paths
            static_paths = list(search_files(self.static_path, lambda file: not file.endswith(".swp")))

            # Set up static progress task
            static_task = self.progress.add_task("[cyan]Copying", total=len(static_paths))

            for static_path in static_paths:
                # Define the target path, directory, and name
                target_path = os.path.join(self.public_path, static_path)
                target_dir = os.path.dirname(target_path)
                target_name = os.path.normpath(target_path.replace(self.public_path, "")[1:])

                # Create description for progress
                description = f"[cyan]Copying[/cyan]   {target_name}"

                # Check for target directory existence
                if not os.path.exists(target_dir):
                    os.makedirs(target_dir)

                # Get timestamp for target
                target_ts = get_timestamp(target_path)

                # If a static item was modified after the last copy, recopy the item
                if get_timestamp(static_path) > target_ts:
                    # Print the progress description
                    self.progress.console.print(description)

                    # Copy the file
                    shutil.copyfile(static_path, target_path)

                # Update the progress meter
                self.progress.update(static_task, description=description, advance=1)

        
# Functions
@Site.filter
def build_link(path: list[str]) -> str:
    # Build a link by defining a path
    return os.path.join(*path).replace(".yaml", ".html")

def search_files(path: str, filter_function: Optional[Callable]=None) -> Iterator[str]:
    # Walk through each dir in the path
    for root, _, files in os.walk(path):
        # For every file
        for file_name in files:
            # Get the path
            file_path = os.path.join(root, file_name)
            # If it matches the filter, add it to the generator
            if not filter_function or filter_function(file_path):
                yield file_path

def get_timestamp(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except FileNotFoundError:
        return 0

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
