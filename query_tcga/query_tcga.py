import requests
import json
import os
import subprocess
import pandas as pd
import io
import numpy as np
import tempfile
import xmltodict

## -- GIVEN -- :
## location of token authorizing download
GDC_TOKEN_PATH = '/Users/jacquelineburos/Downloads/gdc-user-token.2016-09-12T16-39-34-04-00.txt'
## path to gdc-client
GDC_CLIENT_PATH = '/usr/local/bin/gdc-client'
## API endpoint base URL (contains version, etc)
GDC_API_ENDPOINT = 'https://gdc-api.nci.nih.gov/{endpoint}'
## name of cohort to query
# given as parameter
# example: 'TCGA-BLCA'
## location to download files to
GDC_DATA_DIR='data/gdc'
## which types of files to retrieve
# parameter value. defaults to ['Clinical']
VALID_CATEGORIES = [
 "Simple Nucleotide Variation",
 "Copy Number Variation",
 "Biospecimen",
 "Raw Sequencing Data",
 "Transcriptome Profiling",
 "Biospecimen",
 "Clinical",
]
VALID_ENDPOINTS = ['files', 'projects', 'cases', 'annotations']

## -- DO -- :
## 1. generate manifest / list of files to download
## 2. use gdc-client to download files to cwd
## 3. verify downloaded files
## 4. transform files to format needed by Cohorts (not done)


#### ---- generate manifest / list of files to download ---- 

def _construct_filter_parameters(project_name, endpoint_name='files', **kwargs):
    """ construct filter-json given project name & files requested
    
    Examples
    -----------
    
    >>> _construct_filter_parameters(project_name='TCGA-BLCA', data_category='Clinical')
    {'content': [
        {'content': {'field': 'cases.project.project_id', 'value': ['TCGA-BLCA']}, 'op': 'in'},
        {'content': {'field': 'files.data_category', 'value': ['Clinical']}, 'op': 'in'}
        ],
        'op': 'and'}
    
    """
    filt_project = {"op": "in",
            "content": {
                "field": "cases.project.project_id",
                "value": [project_name]
            }
    }

    content_filters = [filt_project]
    query_params = dict(**kwargs)
    for field in query_params:
        field_name = "{endpoint}.{field}".format(endpoint=endpoint_name, field=field)
        _verify_field_values(data_list=_convert_to_list(query_params[field]), field_name=field_name, endpoint_name=endpoint_name)
        next_filter = {"op": "in",
                "content": {
                    "field": field_name,
                    "value": _convert_to_list(query_params[field])
                }
        }
        content_filters.append(next_filter)
    filt = {"op": "and",
            "content": content_filters
            }
    return filt


def _convert_to_list(x):
    """ Convert x to a list if not already a list 

    Examples
    -----------

    >>> _convert_to_list('Clinical')
    ['Clinical']
    >>> _convert_to_list(['Clinical'])
    ['Clinical']
    >>> _convert_to_list(('Clinical','Biospecimen'))
    ['Clinical', 'Biospecimen']

    """
    if not(x):
        return(None)
    elif isinstance(x, list):
        return(x)
    elif isinstance(x, str):
        return([x])
    else:
        return(list(x))

def _compute_start_given_page(page, size):
    """ compute start / from position given page & size
    """
    return (page*size+1)


def _construct_parameters(project_name, size, **kwargs):
    """ Construct query parameters given project name & list of data categories

    >>> _construct_parameters(project_name='TCGA-BLCA', size=5)
    {'filters': 
        '{"content": [{"content": {"value": ["TCGA-BLCA"], "field": "cases.project.project_id"}, "op": "in"}, {"content": {"value": ["Clinical"], "field": "files.data_category"}, "op": "in"}], "op": "and"}',
     'size': 5}
    """
    filt = _construct_filter_parameters(project_name=project_name, **kwargs)
    params = {
        'filters': json.dumps(filt),
        'size': size
        }
    return params


def _search_for_field(search_string, endpoint_name='files'):
    fields = _list_valid_fields(endpoint_name=endpoint_name)
    return [field for field in fields if field.find(search_string)>0]


def _list_valid_fields(endpoint_name='files'):
    """ List allowable fields for this endpoint
    """
    _verify_data_list(data_list=[endpoint_name], allowed_values=VALID_ENDPOINTS)
    endpoint = GDC_API_ENDPOINT.format(endpoint=endpoint_name)+'/_mapping'
    response = requests.get(endpoint)
    response.raise_for_status()
    try:
        field_names = response.json()['_mapping'].keys()
    except:
        _raise_error_parsing_result(response)
    return field_names


def _list_valid_options(field_name, endpoint_name='files',
                        project_name=None, strip_endpoint_from_field_name=True):
    """ List valid options (values) for a field.

    Note that field names are listed without prefix (as 'data_category') when given as a facet. This function
      masks that complexity by stripping out the endpoint from the field name by default. (the default behavior
      can be turned off using parameter `strip_endpoint_from_field_name=False`)

    >>> _list_valid_options('data_category')
    ['Simple Nucleotide Variation',
     'Transcriptome Profiling',
     'Raw Sequencing Data',
     'Copy Number Variation',
     'Biospecimen',
     'Clinical']

    >>> _list_valid_options('files.data_category', endpoint_name='files')
    ['Simple Nucleotide Variation',
      'Transcriptome Profiling',
      'Raw Sequencing Data',
      'Copy Number Variation',
      'Biospecimen',
      'Clinical']

    >>> _list_valid_options('files.data_category', endpoint_name='files', strip_endpoint_from_field_name=False)
    ValueError: Server responded with: {'data': {'pagination': {'from': 1, 'count': 0, 'total': 262293, 'sort': '', 'size': 0, 'page': 1, 'pages': 262293}, 'hits': []}, 'warnings': {'facets': 'unrecognized values: [files.data_category]'}}

     
    """
    # according to https://gdc-docs.nci.nih.gov/API/Users_Guide/Search_and_Retrieval/#filters-specifying-the-query
    # this is the best way to query the endpoint for values
    endpoint = GDC_API_ENDPOINT.format(endpoint=endpoint_name)
    if project_name:
        filt_project = {"op": "in",
            "content": {
                "field": "cases.project.project_id",
                "value": [project_name]  ## for performance reasons, filter to a project
            }
        }
    else:
        filt_project = None
    if strip_endpoint_from_field_name:
        field_name = field_name.replace('{}.'.format(endpoint_name), '')
    params = {'filters': json.dumps(filt_project),
              'facets': field_name,
              'size': 0}
    response = requests.get(endpoint, params=params)
    response.raise_for_status()
    try:
        items = [item['key'] for item in response.json()['data']['aggregations'][field_name]['buckets']]
    except:
        _raise_error_parsing_result(response)
    return items


def _verify_field_name(field_name, endpoint_name):
    """ Verify that field exists for this endpoint

    >>> _verify_field_name(field_name='files.data_category', endpoint_name='files')
    True

    >>> _verify_field_name(field_name='data_category', endpoint_name='files')
    ValueError: Field given was not valid: data_category.
     Some close matches:
            files.data_category
            files.analysis.input_files.data_category
            files.archive.data_category
            files.metadata_files.data_category
            files.index_files.data_category
            files.downstream_analyses.output_files.data_category
    """
    try:
        found = _verify_data_list(field_name, allowed_values=_list_valid_fields(endpoint_name=endpoint_name))
    except ValueError:
        possible_matches = _search_for_field(field_name, endpoint_name=endpoint_name)
        raise ValueError('Field given was not valid: {given}. \n Some close matches: \n\t{matches}'.format(given=field_name,
             matches='\n\t'.join(possible_matches)))
    return found

def _verify_field_values(data_list, field_name, endpoint_name, project_name=None):
    """ Verify that each element in a given list is among the allowed_values 
        for that field/endpoint (& optionally for that project).

    >>> _verify_field_values(['Clinical'], field_name='files.data_category', endpoint_name='files')
    True

    >>> _verify_field_values(['Clinical'], field_name='data_category', endpoint_name='files')
    ValueError: Field given was not valid: data_category.
     Some close matches:
            files.data_category
            files.analysis.input_files.data_category
            files.archive.data_category
            files.metadata_files.data_category
            files.index_files.data_category
            files.downstream_analyses.output_files.data_category
    """ 
    _verify_field_name(field_name=field_name, endpoint_name=endpoint_name)
    valid_options = _list_valid_options(field_name=field_name, endpoint_name=endpoint_name, project_name=project_name)
    return _verify_data_list(data_list=data_list, allowed_values=valid_options)


def _verify_data_list(data_list, allowed_values, message='At least one value given was invalid'):
    """ Verify that each element in a given list is among the allowed_values. 

    >>> _verify_data_list(['TCGA-BLCA'], allowed_values=['Clinical'])
    ValueError: At least one value given was invalid: TCGA-BLCA
    >>> _verify_data_list(['Clinical'], allowed_values=['Clinical', 'Biospecimen'])
    True
    >>> _verify_data_list(['Clinical'], allowed_values=_list_valid_options('data_category'))
    True
    """ 
    data_list = _convert_to_list(data_list)
    if not(all(el in allowed_values for el in data_list)):
        ## identify invalid categories for informative error message
        bad_values = list()
        [bad_values.append(el) for el in data_list if not(el in allowed_values)]
        raise ValueError('{message}: {bad_values}'.format(bad_values=', '.join(bad_values), message=message))
    return True


def _raise_error_parsing_result(response):
    try:
        raise ValueError('Error parsing returned object: {}'.format(response.json()['warnings']))
    except:
        raise ValueError('Server responded with: {}'.format(response.json()))


def _get_num_pages(project_name, size, **kwargs):
    """ Get total number of pages for given criteria

    >>> _get_num_pages('TCGA-BLCA', data_category=['Clinical'], size=5)
    83

    """
    endpoint = GDC_API_ENDPOINT.format(endpoint='files')
    params = _construct_parameters(project_name=project_name, size=size, **kwargs)
    response = requests.get(endpoint, params=params)
    response.raise_for_status()
    try:
        pages = response.json()['data']['pagination']['pages']
    except:
        _raise_error_parsing_result(response)
    return pages


def _get_manifest_once(project_name, size, page=0, **kwargs):
    """ Single get for manifest of files matching project_name & categories

    >>> _get_manifest_once('TCGA-BLCA', data_category=['Clinical'], size=5)
    <Response [200]>
    """ 
    endpoint = GDC_API_ENDPOINT.format(endpoint='files')
    params = _construct_parameters(project_name=project_name, size=size, **kwargs)
    from_param = _compute_start_given_page(page=page, size=size)
    extra_params = {
        'return_type': 'manifest',
        'from': from_param,
        'sort': 'file_name:asc',
        }
    # requests URL-encodes automatically
    response = requests.get(endpoint, params=dict(params, **extra_params))
    response.raise_for_status()
    return response


def get_manifest(project_name, size=100, pages=None, **kwargs):
    """ get manifest containing for all results matching project_name & categories

    >>> get_manifest(project_name='TCGA-BLCA', data_category=['Clinical'], pages=2, size=2)
    'id\tfilename\tmd5\tsize\tstate\n...'
    """
    output = io.StringIO()
    if not(pages):
        pages = _get_num_pages(project_name=project_name, size=size, **kwargs)
    for page in np.arange(pages):
        response = _get_manifest_once(project_name=project_name, page=page, size=size, **kwargs)
        response_text = response.text.splitlines()
        if page>0:
            del response_text[0]
        [output.write(line+'\n') for line in response_text]
    return output.getvalue()


#### ---- download files ---- 

def _mkdir_if_not_exists(dir):
    if not(os.path.exists(dir)):
        sub_dir = ''
        for dir_name in os.path.split(dir):
            sub_dir = os.path.join(sub_dir, dir_name)
            if not(os.path.exists(sub_dir)):
                os.mkdir(sub_dir)


def _download_files(project_name, data_category, page_size=50, max_pages=None, data_dir=GDC_DATA_DIR, **kwargs):
    """ Download files for this project to the current working directory
        1. Query API to get manifest file containing all files matching criteria
        2. Use gdc-client to download files to current working directory
        3. Verify that files downloaded as expected

    >>> _download_files(project_name='TCGA-BLCA', data_category='Clinical', max_pages=1, page_size=5)
    100% [##############################] Time: 0:00:00
    100% [#################] Time: 0:00:00 297.30 kB/s
    100% [##############################] Time: 0:00:00
    100% [#################] Time: 0:00:00 532.74 kB/s
    100% [##############################] Time: 0:00:00
    100% [#################] Time: 0:00:00 394.49 kB/s

    """
    _mkdir_if_not_exists(data_dir)
    manifest_contents = get_manifest(project_name=project_name,
                                       data_category=data_category,
                                       size=page_size, pages=max_pages, **kwargs)
    manifest_file = tempfile.NamedTemporaryFile()
    try:
        # write manifest contents to disk
        manifest_file.write(manifest_contents.encode())
        manifest_file.flush()
        # call gdc-client to download contents
        # {gdc_client} download -m {manifest_file} -t {auth_token}
        exe_bash = [GDC_CLIENT_PATH, 'download', '-m', manifest_file.name, '-t', GDC_TOKEN_PATH]
        if subprocess.check_call(exe_bash, cwd=data_dir):
            subprocess.call(exe_bash, cwd=data_dir)
        # Verify contents have been downloaded
        verify_download(manifest_file.name, data_dir=data_dir)
    finally:
        manifest_file.close()  
    return True


def download_clinical_files(project_name, **kwargs):
    """ Download clinical files for this project to the current working directory
        1. Query API to get manifest file containing all files matching criteria
        2. Use gdc-client to download files to current working directory
        3. Verify that files downloaded as expected
    """
    return _download_files(project_name=project_name, data_category=['Clinical'], **kwargs)


#### ---- verify downloaded files ---- 

def _read_manifest_data(manifest_file):
    """ Read file contents into pandas dataframe
    """
    manifest_data = pd.read_table(manifest_file, sep='\t')
    return manifest_data


def _verify_download_single_file(row, data_dir=os.getcwd()):
    """ Verify that the file indicated in the manifest exists in data_dir 
    """
    file_name = os.path.join(data_dir, row['id'], row['filename'])
    return os.path.exists(file_name)


def verify_download(manifest_file, data_dir=os.getcwd()):
    """ Verify that files listed in the manifest exist in data_dir
    """
    manifest_data = _read_manifest_data(manifest_file)
    verification = manifest_data.apply(lambda row: _verify_download_single_file(row, data_dir=data_dir), axis=1)
    if (all(verification)):
        return True
    else:
        ## TODO identify which rows failed
        ## TODO format error message to list files that failed to download
        raise ValueError("Some files failed to download.")


#### ---- transform downloaded files to Cohorts-friendly format ----


def _parse_tcga_clinical(xml_file_path, project_name='TCGA-BLCA'):
    """ Parse incoming TCGA data; return dict suitable to be processed into a Pandas dataframe
    """
    # read document
    with open(xml_file_path) as fd:
        doc = xmltodict.parse(fd.read())

    # identify study-prefix, given project_name
    study_prefix = project_name.lower().replace('tcga-','')
    # identify head-node, in case name changes
    head_node_search_pattern = '{prefix}:tcga'.format(prefix=study_prefix)
    head_node = [key for key in doc.keys() if key.contains(head_node_search_pattern)]
    if (len(head_node) != 1):
        raise ValueError('Head node ({head}) could not be identified. Candidate keys include: {keys} '.format(head=head_node_search_pattern, keys=','.split(doc.keys())))
    # identify data elements to extract
    # should be a dict structured as {'field_name': ['node1','node2', ...]}
    data_elements = doc[head_node[0]]['{prefix}:patient'.format(prefix=study_prefix)]
    return data_elements


if __name__ == "__main__":
    import doctest
    doctest.testmod()