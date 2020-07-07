'''
Written by: Thomas Munzer (tmunzer@juniper.net)
Github repository: https://github.com/tmunzer/Mist_library/

Python script to restore site template/backup file.
You can use the script "org_site_backup.py" to generate the backup file from an
existing organization.

This script will not overide existing objects. If you already configured objects in the 
destination organisation, new objects will be reused or created. If you want to "reset" the 
destination organization, you can use the script "org_conf_zeroise.py".
This script is trying to maintain objects integrity as much as possible. To do so, when 
an object is referencing another object by its ID, the script will replace be ID from 
the original organization by the corresponding ID from the destination org.

You can run the script with the command "python3 site_conf_import.py"

The script has 3 different steps:
1) admin login
2) choose the destination org
3) choose the backup/template to restore
all the objects will be created from the json file. 
'''

#### PARAMETERS #####

session_file = ""
backup_directory = "./site_backup/"

org_id = ""
#### IMPORTS ####

import mlib as mist_lib
from mlib.__debug import Console
from mlib import cli
from tabulate import tabulate
import json
import os.path

#### CONSTANTS ####
console = Console(6)
backup_file = "./site_conf_file.json"
file_prefix = ".".join(backup_file.split(".")[:-1])


#### GLOBAL VARS ####


rftemplate_id = None
sitegroup_ids = []
map_id_dict = {}
wlan_id_dict = {}
wxtags_id_dict = {}
secpolicy_id = None
alarmtemplate_id = None
networktemplate_id = None

#### FUNCTIONS ####

def _get_new_id(old_id, new_ids_dict):
    if old_id in new_ids_dict:
        new_id = new_ids_dict[old_id]
        console.debug("Replacing id %s with id %s" %(old_id, new_id))
        return new_id
    else:
        console.debug("Unable to replace id %s" %old_id)
        return None


def _replace_id(old_ids_list, new_ids_dict):
    if old_ids_list == None:
        return None
    if old_ids_list == {}:
        return {}
    elif type(old_ids_list) == str:
        return _get_new_id(old_ids_list, new_ids_dict)
    elif type(old_ids_list) == list:
        new_ids_list = []
        for old_id in old_ids_list:
            new_ids_list.append(_get_new_id(old_id, new_ids_dict))
        return new_ids_list
    else:
        console.error("Unable to replace ids: %s" % old_ids_list)



def _clean_ids(data):
    if "id" in data:
        del data["id"]
    if "org_id" in data:
        del data["org_id"]
    if "modified_time" in data:
        del data["modified_time"]
    if "created_time" in data:
        del data["created_time"]
    return data


def _common_restore(mist_session, site_name, site_id, object_name, data):
    console.info("SITE %s > Creating %s..." %(site_name, object_name))    
    if "id" in data:
        old_id = data["id"]
    else: 
        old_id = None
    data = _clean_ids(data)
    module = mist_lib.requests.route("sites", object_name)
    result = module.create(mist_session, site_id, data)["result"]    
    if "id" in result:
        new_id = result["id"]
    return {old_id: new_id}


def _wlan_restore(mist_session, site_name, new_site_id, data, old_site_id):
    if "wxtunnel_id" in data:
        data["wxtunnel_id"] = _replace_id(data["wxtunnel_id"], wxtags_id_dict)
    if "app_limit" in data and "wxtag_ids" in data["app_limit"]:
        data["app_limit"]["wxtag_ids"] = _replace_id(data["app_limit"]["wxtag_ids"], wxtags_id_dict)
    ids = _common_restore(mist_session, site_name, new_site_id, 'wlans', data)
    old_wlan_id = next(iter(ids))
    new_wlan_id = ids[old_wlan_id]
    _wlan_restore_portal(mist_session, site_name, new_site_id, old_site_id, old_wlan_id, new_wlan_id)
    wlan_id_dict.update(ids)

def _wlan_restore_portal(mist_session, site_name,level_id, old_site_id, old_wlan_id, new_wlan_id): 
        if old_site_id == None:
            portal_file_name = "%s_wlan_%s.json" %(file_prefix, old_wlan_id)
            portal_image = "%s_wlan_%s.png" %(file_prefix, old_wlan_id)
            module = mist_lib.requests.route("orgs", "wlans")
        else:
            portal_file_name = "%s_site_%s_wlan_%s.json" %(file_prefix, old_site_id, old_wlan_id) 
            portal_image = "%s_site_%s_wlan_%s.png" %(file_prefix, old_site_id, old_wlan_id)
            module = mist_lib.requests.route("sites", "wlans")

        if site_name: site_text = " SITE %s >" %(site_name)
        else: site_text = "" 
        if os.path.isfile(portal_file_name):
            console.info("SITE %s >%s Creating portal template %s..." %(site_name, site_text, portal_file_name))
            template = open(portal_file_name, 'r')
            template = json.load(template)
            module.set_portal_template(mist_session, level_id, new_wlan_id, template)
        else: console.warning("SITE %s > %s Portal template %s not found" %(site_name, site_text, portal_file_name))
        if os.path.isfile(portal_image):
            console.info("SITE %s > %s Creating portal image %s..." %(site_name, site_text, portal_image))
            module.add_portal_image(mist_session, level_id, new_wlan_id, portal_image)
        else: console.warning("SITE %s > %s Portal image %s not found" %(site_name, site_text, portal_image))
        

def _restore_site(mist_session, org_id, org_name, site_name, backup):
    old_site_id = backup["site"]["info"]["id"]
    new_site_id = None
    assigned_sitegroup_ids = []
    assigned_rftempate_id = None
    assigned_secpolicy_id = None
    assigned_alarmtemplate_id = None
    assigned_networktemplate_id = None

    ### lookup for site groups ###
    console.info("ORG %s > Processing site groups..." %(org_name))
    if not backup["sitegroup_names"] == []:
        available_sitegroups = mist_lib.requests.orgs.sitegroups.get(mist_session, org_id)["result"]
        for sitegroup_name in backup["sitegroup_names"]:
            try:
                new_sitegroup_id = next(item["id"] for item in available_sitegroups if item["name"]==sitegroup_name)
                console.info("ORG %s > Site group \"%s\" found in the new org..." %(org_name, sitegroup_name))
            except: 
                console.notice("ORG %s > Site group \"%s\" not found in the new org... Creating it..." %(org_name, sitegroup_name))
                new_sitegroup_id = mist_lib.requests.orgs.sitegroups.create(mist_session, org_id, {"name":sitegroup_name})
                console.info("ORG %s > Site group \"%s\" created" %(org_name, sitegroup_name))
            finally:
                assigned_sitegroup_ids.append(new_sitegroup_id)

    ### lookup for RF templates ###
    console.info("ORG %s > Processing RF Template..." %(org_name))
    if not backup["rftemplate"] == {}:
        available_rftemplates = mist_lib.requests.orgs.rftemplates.get(mist_session, org_id)["result"]
        try:
            new_rftemplate_id = next(item["id"] for item in available_rftemplates if item["name"]==backup["rftemplate"]["name"])
            console.info("ORG %s > RF Template \"%s\" found in the new org..." %(org_name, backup["rftemplate"]["name"]))
        except: 
            console.notice("ORG %s > RF Template \"%s\" not found in the new org... Creating it..." %(org_name, backup["rftemplate"]["name"]))
            new_rftemplate_id = mist_lib.requests.orgs.rftemplates.create(mist_session, org_id, backup["rftemplate"])
            console.info("ORG %s > RF Template \"%s\" created" %(org_name, backup["rftemplate"]["name"]))
        finally:
            assigned_rftempate_id = new_rftemplate_id

    ### lookup for security policy ###
    console.info("ORG %s > Processing Security Policy..." %(org_name))
    if not backup["secpolicy"] == {}:
        available_secpolicies = mist_lib.requests.orgs.secpolicies.get(mist_session, org_id)["result"]
        try:
            new_secpolicy_id = next(item["id"] for item in available_secpolicies if item["name"]==backup["secpolicy"]["name"])
            console.info("ORG %s > Security Policy \"%s\" found in the new org..." %(org_name, backup["secpolicy"]["name"]))
        except: 
            console.notice("ORG %s > Security Policy \"%s\" not found in the new org... Creating it..." %(org_name, backup["secpolicy"]["name"]))
            new_secpolicy_id = mist_lib.requests.orgs.secpolicies.create(mist_session, org_id, backup["secpolicy"])
            console.info("ORG %s > Security Policy \"%s\" created" %(org_name, backup["secpolicy"]["name"]))
        finally:
            assigned_secpolicy_id = new_secpolicy_id

    ### lookup for Alarm templates ###
    console.info("ORG %s > Processing Alarm Template..." %(org_name))
    if not backup["alarmtemplate"] == {}:
        available_alarmtemplates = mist_lib.requests.orgs.alarmtemplates.get(mist_session, org_id)["result"]
        try:
            new_alarmtemplate_id = next(item["id"] for item in available_alarmtemplates if item["name"]==backup["alarmtemplate"]["name"])
            console.info("ORG %s > Alarm Template \"%s\" found in the new org..." %(org_name, backup["alarmtemplate"]["name"]))
        except: 
            console.notice("ORG %s > Alarm Template \"%s\" not found in the new org... Creating it..." %(org_name, backup["alarmtemplate"]["name"]))
            new_alarmtemplate_id = mist_lib.requests.orgs.alarmtemplates.create(mist_session, org_id, backup["alarmtemplate"])
            console.info("ORG %s > Alarm Template \"%s\" created" %(org_name, backup["alarmtemplate"]["name"]))
        finally:
            assigned_alarmtemplate_id = new_alarmtemplate_id

    ### lookup for network templates ###
    console.info("ORG %s > Processing Network Template..." %(org_name))
    if not backup["networktemplate"] == {}:
        available_networktemplates = mist_lib.requests.orgs.networktemplates.get(mist_session, org_id)["result"]
        try:
            new_networktemplate_id = next(item["id"] for item in available_networktemplates if item["name"]==backup["networktemplate"]["name"])
            console.info("ORG %s > Network Template \"%s\" found in the new org..." %(org_name, backup["networktemplate"]["name"]))
        except: 
            console.notice("ORG %s > Network Template \"%s\" not found in the new org... Creating it..." %(org_name, backup["networktemplate"]["name"]))
            new_networktemplate_id = mist_lib.requests.orgs.networktemplates.create(mist_session, org_id, backup["networktemplate"])
            console.info("ORG %s > Network Template \"%s\" created" %(org_name, backup["networktemplate"]["name"]))
        finally:
            assigned_networktemplate_id = new_networktemplate_id

    ### restore site ###
    new_site = backup["site"]["info"]
    new_site["name"] = site_name
    new_site["sitegroup_ids"] = assigned_sitegroup_ids
    new_site["rftemplate_id"] = assigned_rftempate_id
    new_site["secpolicy_id"] = assigned_secpolicy_id
    new_site["alarmtemplate_id"] = assigned_alarmtemplate_id
    new_site["networktemplate_id"] = assigned_networktemplate_id
    console.info("ORG %s > Creating site %s in the new org..." %(org_name, site_name))
    new_site_id = mist_lib.requests.orgs.sites.create(mist_session, org_id, new_site)["result"]["id"]

    ### set site settings ###
    console.info("ORG %s > SITE %s > Configuring site settings..." %(org_name, site_name))
    mist_lib.requests.sites.settings.update(mist_session, new_site_id, backup["site"]["settings"])

    ####  SITES MAIN  ####
    data = backup["site"]
    if "maps" in data:
        for sub_data in data["maps"]:
            sub_data["site_id"] = new_site_id
            ids = _common_restore(mist_session, site_name, new_site_id, 'maps', sub_data)
            map_id_dict.update(ids)

            old_map_id = next(iter(ids))
            new_map_id = ids[old_map_id]

            image_name = "%s_site_%s_map_%s.png" %(file_prefix, old_site_id, old_map_id)
            if os.path.isfile(image_name):
                console.info("Image %s will be restored to map %s" %(image_name, new_map_id))
                mist_lib.requests.sites.maps.add_image(mist_session, new_site_id, new_map_id, image_name)
            else:
                console.info("No image found for old map id %s" % old_map_id)


    if "assetfilters" in data:
        for sub_data in data["assetfilters"]:
            _common_restore(mist_session, site_name, new_site_id, 'assetfilters', sub_data)

    if "assets" in data:
        for sub_data in data["assets"]:
            _common_restore(mist_session, site_name, new_site_id, 'assets', sub_data)

    if "beacons" in data:
        for sub_data in data["beacons"]:
            sub_data["map_id"] = _replace_id(sub_data["map_id"], map_id_dict)
            _common_restore(mist_session, site_name, new_site_id, 'beacons', sub_data)

    if "psks" in data:
        for sub_data in data["psks"]:
            sub_data["site_id"] = new_site_id
            _common_restore(mist_session, site_name, new_site_id, 'psks', sub_data)

    if "rssizones" in data:
        for sub_data in data["rssizones"]:
            _common_restore(mist_session, site_name, new_site_id, 'rssizones', sub_data)

    if "vbeacons" in data:
        for sub_data in data["vbeacons"]:
            sub_data["map_id"] = _replace_id(sub_data["map_id"], map_id_dict)
            _common_restore(mist_session, site_name, new_site_id, 'vbeacons', sub_data)

    if "webhooks" in data:
        for sub_data in data["webhooks"]:
            _common_restore(mist_session, site_name, new_site_id, 'webhooks', sub_data)

    if "wxtunnels" in data:
        for sub_data in data["wxtunnels"]:
            _common_restore(mist_session, site_name, new_site_id, 'wxtunnels', sub_data)

    if "zones" in data:
        for sub_data in data["zones"]:
            sub_data["map_id"] = _replace_id(sub_data["map_id"], map_id_dict)
            _common_restore(mist_session, site_name, new_site_id,  'zones', sub_data)
    
    if "wlans" in data:
        for sub_data in data["wlans"]:
            _wlan_restore(mist_session, site_name, new_site_id, sub_data, old_site_id)

    if "wxtags" in data:
        for sub_data in data["wxtags"]:
            if sub_data["match"] == "wlan_id":
                _replace_id(sub_data["values"], wlan_id_dict)
            ids = _common_restore(mist_session, site_name, new_site_id, 'wxtags', sub_data)
            wxtags_id_dict.update(ids)

    if "wxrules" in data:
        for sub_data in data["wxrules"]:
            if "src_wxtags" in sub_data:
                sub_data["src_wxtags"] = _replace_id(sub_data["src_wxtags"], wxtags_id_dict)
            if "dst_allow_wxtags" in sub_data:
                sub_data["dst_allow_wxtags"] = _replace_id(sub_data["dst_allow_wxtags"], wxtags_id_dict)
            if "dst_deny_wxtags" in sub_data:
                sub_data["dst_deny_wxtags"] = _replace_id(sub_data["dst_deny_wxtags"], wxtags_id_dict)
            _common_restore(mist_session, site_name, new_site_id, 'wxrules', sub_data)

    

def _display_warning(message):
    resp = "x"
    while not resp.lower() in ["y", "n", ""]:
        print()
        resp = input(message)
    if not resp.lower()=="y":
        console.warning("Interruption... Exiting...")
        exit(0)

def _select_backup_folder(folders):   
    i = 0
    while i < len(folders):
        print("%s) %s" %(i, folders[i]))
        i += 1
    folder = None
    while folder == None:
        resp = input("Please select a folder (0-%s, or q to quit)? "  %i)
        if resp.lower() == "q":
            console.warning("Interruption... Exiting...")
            exit(0)
        try:
            respi = int(resp)
            if respi >= 0 and respi <= i:
                folder = folders[respi]
            else:
                print("The entry value \"%s\" is not valid. Please try again...")
        except:
            print("Only numbers are allowed. Please try again...")
    os.chdir(folder)

def _got_to_site_folder():
    folders = []
    for entry in os.listdir("./"):
        if os.path.isdir(os.path.join("./", entry)):
            folders.append(entry)
    print()
    print("Available sites templates/backup folders:") 
    _select_backup_folder(folders)

def _go_to_backup_folder():
    os.chdir(os.getcwd())
    os.chdir(backup_directory)
    folders = []
    for entry in os.listdir("./"):
        if os.path.isdir(os.path.join("./", entry)):
            folders.append(entry)    
    print()
    print("Available templates/backups folders:")
    _select_backup_folder(folders)
    _got_to_site_folder()

def _print_warning():
    print(""" 

__          __     _____  _   _ _____ _   _  _____ 
\ \        / /\   |  __ \| \ | |_   _| \ | |/ ____|
 \ \  /\  / /  \  | |__) |  \| | | | |  \| | |  __ 
  \ \/  \/ / /\ \ |  _  /| . ` | | | | . ` | | |_ |
   \  /\  / ____ \| | \ \| |\  |_| |_| |\  | |__| |
    \/  \/_/    \_\_|  \_\_| \_|_____|_| \_|\_____|

This script is still in BETA. It won't hurt your original
organization or site, but the restoration may partially fail. 
It's your responsability to validate the importation result!


""")

def _check_org_name(org_name):
    while True:
        print()
        resp = input("To avoid any error, please confirm the current destination orgnization name: ")
        if resp == org_name:
            return True
        else:
            console.warning("The orgnization names do not match... Please try again...")
        print()


def _check_site_exists(org_id, backup):
    site_name_to_create = backup["site"]["info"]["name"]
    existing_sites = mist_lib.requests.orgs.sites.get(mist_session, org_id)["result"]
    try:
        site_id = next(item["id"] for item in existing_sites if item["name"] == site_name_to_create)
        while True:
            print()
            console.warning("Site \"%s\" already exists in the destination org! " %(site_name_to_create))
            response = input("What do you want to do: (r)eplace, re(n)ame, (a)bort?")
            if response.lower() == "a":
                console.warning("Interruption... Exiting...")
                exit(0)
            elif response.lower() == "r":
                console.warning("I'm still working on this part... Please try with a later version...")
            elif response.lower() == "n":
                new_name = input("New name: ")
                return new_name
    except:
        return site_name_to_create


def start_restore_org(mist_session, org_id, org_name, check_org_name=True, in_backup_folder=False):
    if check_org_name: _check_org_name(org_name)
    if not in_backup_folder: _go_to_backup_folder()    
    try:
        with open(backup_file) as f:
            backup = json.load(f)
    except: 
        console.error("unable to load the file backup %s" %(backup_file))
        exit(1)
    finally:
        if backup:
            console.info("File %s loaded succesfully." %backup_file)
            site_name_to_create = _check_site_exists(org_id, backup)

            _display_warning("Are you sure about this? Do you want to import the site configuration into the organization %s with the id %s (y/N)? " %(org_name, org_id))
            _restore_site(mist_session, org_id, org_name, site_name_to_create, backup)
        
            print()
            console.notice("Restoration process finished...")

def start(mist_session, org_id=None):
    if org_id == "":
        org_id = cli.select_org(mist_session)[0]
    org_name = mist_lib.requests.orgs.info.get(mist_session, org_id)["result"]["name"]
    start_restore_org(mist_session, org_id, org_name)


#### SCRIPT ENTRYPOINT ####


if __name__ == "__main__":
    mist_session = mist_lib.Mist_Session(session_file)
    start(mist_session, org_id)


