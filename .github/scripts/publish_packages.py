from collections import namedtuple
import glob
import os
import yaml
import shutil
import tempfile
import hashlib
import subprocess
import time
import json
import re
from typing import TypedDict


Package = namedtuple('Package', 'name version location title description author')
UploadedPackage = namedtuple('UploadedPackage', 'name version')

RELEASES_VERSION = "v1.0.0"

def get_released_packages() -> list[UploadedPackage]:
  result = subprocess.run(['gh', 'release', 'view', "--json", "assets"], stdout=subprocess.PIPE)
  json_assets = result.stdout.decode('utf-8')
  assets = json.loads(json_assets)["assets"]

  packages = []
  for package in assets:
    file_name = package["name"]
    match = re.search('(?P<name>.*?)-(?P<version>\d+.\d+.\d+).zip', file_name)
    if match is not None:
      name = match.group("name")
      version = match.group("version")

      packages.append(UploadedPackage(name, version))

  return packages 

def get_repository_packages() -> list[Package]:
  packages = []
  for path in glob.glob("packages/*/*/_manifest.yml"):
    package_dir = os.path.dirname(path)
    with open(path, 'r') as stream:
      try:
        manifest = yaml.safe_load(stream)
        name = manifest["name"]
        version = manifest["version"]
        title = manifest["title"]
        description = manifest["description"]
        author = manifest["author"]
        package = Package(name, version, package_dir, title, description, author)
        packages.append(package)
      except yaml.YAMLError as exc:
        print("Exception parsing YAML ", exc)
  return packages

def calculate_missing_packages(released: list[Package], repository: list[Package]) -> list[Package]:
  published_packages: set[str] = set()
  for package in released:
    published_packages.add(f"{package.name}@{package.version}")
  
  missing_packages = []
  for package in repository:
    package_id = f"{package.name}@{package.version}"
    if package_id not in published_packages:
      missing_packages.append(package)
  
  return missing_packages

def calculate_sha256(filename) -> str:
  sha256_hash = hashlib.sha256()
  with open(filename,"rb") as f:
    for byte_block in iter(lambda: f.read(4096),b""):
      sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def create_archive(package: Package)-> tuple[str, str, str]: 
  temp_dir = tempfile.gettempdir()
  target_name = os.path.join(temp_dir, f"{package.name}-{package.version}")
  shutil.make_archive(target_name, 'zip', package.location)
  
  target_file = f"{target_name}.zip"
  hash = calculate_sha256(target_file)
  target_sha_file = os.path.join(temp_dir, f"{package.name}-{package.version}-sha256.txt")

  with open(target_sha_file, "w") as file:
    file.write(hash)
  
  return (target_file, target_sha_file, hash)

def upload_to_releases(archive_path, archive_hash_path):
  subprocess.run(["gh", "release", "upload", RELEASES_VERSION, archive_hash_path, archive_path, "--clobber" ])

class IndexPackageEntry(TypedDict):
  name: str
  author: str
  description: str
  version: str
  title: str
  archive_url: str
  archive_sha256_url: str


def update_index(repository: list[Package]):
  packages: list[IndexPackageEntry] = []

  for package in repository:
    packages.append({
      "name": package.name,
      "author": package.author,
      "description": package.description,
      "title": package.title,
      "version": package.version,
      "archive_url": f"https://github.com/espanso/hub/releases/download/latest/{package.name}-{package.version}.zip",
      "archive_sha256_url": f"https://github.com/espanso/hub/releases/download/latest/{package.name}-{package.version}-sha256.txt",
    })
  
  index = {
    "lastUpdate": round(time.time()),
    "packages": packages,
  }

  json_index = json.dumps(index)

  temp_dir = tempfile.gettempdir()
  target_file = os.path.join(temp_dir, "package_index.json")
  
  with open(target_file, "w") as file:
    file.write(json_index)

  subprocess.run(["gh", "release", "upload", RELEASES_VERSION, target_file, "--clobber"])


print("Reading packages from repository...")
repository_packages = get_repository_packages()

print("Obtaining released packages from GitHub Releases...")
released_packages = get_released_packages()

print("")
print("Calculating delta...")
missing_packages = calculate_missing_packages(released_packages, repository_packages)

if len(missing_packages) == 0:
  print("Packages are already up-to-date")
  quit(0)

print("")
print("Packages to publish:")
for package in missing_packages:
  print(f"--> {package.name}@{package.version}")

  archive_path, archive_hash_path, archive_hash = create_archive(package)

  print(f"Created archive {archive_path}, hash: {archive_hash}")

  print(f"Uploading to Github Releases...")
  upload_to_releases(archive_path, archive_hash_path)
  print("Done!")

print("")
print("Updating index...")
update_index(repository_packages)

print("Done!")