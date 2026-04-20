import json
import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(__file__))
CONFIG_PATH = os.path.join(ROOT, 'config', 'poi_config.json')

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s %(name)s %(message)s')
    logger = logging.getLogger('run_full_incremental_verbose')

    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
    except Exception as e:
        logger.exception('Failed to load config: %s', CONFIG_PATH)
        sys.exit(2)

    # Ensure debug mode for verbose logging
    cfg['debug'] = True

    try:
        import importlib.util
        MAP_PF_PATH = os.path.join(ROOT, 'map_poi_fetcher.py')
        spec = importlib.util.spec_from_file_location('map_poi_fetcher', MAP_PF_PATH)
        map_poi_fetcher = importlib.util.module_from_spec(spec)
        # Ensure project root is on sys.path so local imports resolve
        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)
        spec.loader.exec_module(map_poi_fetcher)
    except Exception:
        logger.exception('Failed to load map_poi_fetcher from %s', MAP_PF_PATH)
        sys.exit(2)

    results = []
    for task in cfg.get('tasks', []):
        if not task.get('enabled', True):
            logger.info('Skipping disabled task: %s', task.get('name'))
            continue
        if 'provider' not in task:
            logger.error('Task missing provider, skipping: %s', task.get('name'))
            continue

        logger.info('Running task: %s (provider=%s, incremental=%s)', task.get('name'), task.get('provider'), cfg.get('incremental'))
        try:
            out = map_poi_fetcher.run_task(task, cfg, mode='manual')
            logger.info('Task finished: %s -> %s', task.get('name'), out.get('status'))
            results.append({'task': task.get('name'), 'result': out})
        except Exception:
            logger.exception('Task failed: %s', task.get('name'))
            results.append({'task': task.get('name'), 'result': 'exception'})

    logger.info('All tasks complete. Summary:')
    for r in results:
        logger.info('%s -> %s', r['task'], r['result'])

    sys.exit(0)
