import sys, os, json, re
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from config_loader import load_config
from poi_utils import merge_keywords

cfg = load_config('config/poi_config.json')
task = next((t for t in cfg.get('tasks', []) if t.get('name') == '河北'), None)
print('Task:', json.dumps(task, ensure_ascii=False))
resources = task.get('resources') if task.get('resources') else cfg.get('resources', [])
if not isinstance(resources, list):
    resources = [resources]

subtasks = []

for resource in resources:
    # build keywords
    try:
        if isinstance(resource, str) and (resource in cfg.get('keywords', {}) or resource in ['gas_station','service_area','hospital','repair_factory']):
            keywords = merge_keywords(cfg, resource)
        else:
            keywords = [p.strip() for p in re.split(r"[,，]", str(resource)) if p.strip()]
    except Exception:
        keywords = [p.strip() for p in re.split(r"[,，]", str(resource)) if p.strip()]
    print('resource', resource, 'keywords', keywords)
    for keyword in keywords:
        resolved = None
        # simulate resolve_data_type: try mapping files
        # here simply use resource as pass_resource if resource looks numeric else resource
        pass_resource = resource
        # area_type admin
        regions_list = task.get('admin_regions') if task.get('admin_regions') else [task.get('admin_region', {})]
        norm_regions = []
        for a in regions_list:
            try:
                prov_name = a.get('province', '') if isinstance(a, dict) else ''
                cit = a.get('city', '') if isinstance(a, dict) else ''
                cnty = a.get('county', '') if isinstance(a, dict) else ''
                if isinstance(cit, str) and cit.strip() == '全部':
                    cit = ''
                if isinstance(cnty, str) and cnty.strip() == '全部':
                    cnty = ''
                norm_regions.append({'province': prov_name, 'city': cit, 'county': cnty})
            except Exception:
                norm_regions.append({'province': a.get('province', '') if isinstance(a, dict) else '', 'city': '', 'county': ''})
        regions_list = norm_regions
        for admin in regions_list:
            prov_name = admin.get('province','')
            cit = admin.get('city', None)
            cnty = admin.get('county', None)
            if cit == "":
                #省级展开 (not our case)
                pass
            elif cit and cnty == "":
                # city-level expand (not our case)
                pass
            else:
                call_kw = keyword
                call_place = pass_resource
                subtasks.append({'call_kw': call_kw, 'call_place': call_place, 'admin': admin, 'area_label': f"{prov_name} / {cit} / {cnty}", 'level_label':'single', 'resource':resource})

print('Generated subtasks:', json.dumps(subtasks, ensure_ascii=False, indent=2))
