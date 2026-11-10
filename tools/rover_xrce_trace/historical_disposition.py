"""Historical diagnostic disposition with explicit, metadata-only project integration.

No start/stop/ROS/control path. Dry-run reads under existing project locks;
apply-reviewed writes a separate audit only. Authorization is a scope declaration,
not authenticated human identity. OfflineDisposition remains a /tmp test harness.
"""
from copy import deepcopy
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import time

from tools import vehicle_execution_lock as locks
from .session_precheck import closure_archive_reference, verified_closure_archive, classify_last_session, HISTORICAL_OWNER, FAILED_OWNER, HISTORICAL_MANIFEST, FAILED_MANIFEST

CLASS = 'HISTORICAL_INFRASTRUCTURE_CLOSED_DIAGNOSTICS_INCOMPLETE'
SUCCESSOR_SCHEMA='tfg.diagnostic-disposition/4'
SUCCESSOR_PROTOCOL='EXACT_CONSUMER_SUCCESSOR_V1'
RESOURCE_READER_SUCCESSOR_PROTOCOL='PRESENT_RESOURCE_READER_SUCCESSOR_V1'
RESOURCE_READER_PIN='tools/rover_xrce_trace/present_resources.py'
RESOURCE_READER_LEGACY_SHA256='23550ccfd411ed14aa7b24fe44cf7e2ac80e7a9751c526a6ff0c4c99b1d721c7'
RESOURCE_READER_CURRENT_SHA256='5f73e030885eb8118b516e00bd97a3ac7c690458a536e733391d5b20677b4d07'
RESOURCE_READER_INTRODUCER='d53f508ea312c4cd63d916a31890299ae35a4090'
RESOURCE_READER_REASON='Classify TCP states explicitly; retain TIME_WAIT as unavailable cooldown'
# A host reboot necessarily changes these execution facts and nothing else.
# Persistent container identity, history, proof, effects and flags stay exact.
BOOT_SUCCESSOR_PROTOCOL='HOST_BOOT_RECOVERY_SUCCESSOR_V1'
BOOT_FIELDS=('host_boot_id','environment_execution','resource_context','reader_hashes')
# Besides the consumer pin, only the profile catalogue may be revised (new profiles).
# Process/resource/backend readers stay fixed. Every revision needs a new exact authorization.
REVISABLE_PINS=('tools/rover_xrce_trace/historical_disposition.py','tools/simulation_profiles.py')
SUCCESSOR_PIN='tools/rover_xrce_trace/historical_disposition.py'
# Reviewed predecessor implementation, not a descriptor/UUID exemption.
SUCCESSOR_FROM='0b9ba1a91a3c09fa0a6d379051a5872e5eb6079c305263af33e26f3d27afed24'


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def dry_run(records, current=None, *, now=None, clock=None):
    """Pure assessment; no locks/files/processes created, even when evidence fails."""
    if records.get('recovery_basis'):
        from .present_recovery import BASIS,review
        if records['recovery_basis']!=BASIS:
            return {'status':'BLOCKED','reason':'Unknown recovery basis','opening_authorized':False}
        report=review(records,current or {},now=now,clock=clock)
        if current and current.get('consumer_predecessor') is not None:
            return _successor_report(report,current,now=now,clock=clock)
        return report
    now = (clock or time.monotonic)() if now is None else now
    required = {'target','start_operation','stop_operation','environment_reference',
                'environment','inventory','selection','launch','monitor'}
    current = current or {}
    observed = current.get('environment_observation')
    missing = sorted(required - records.keys())
    state = observed.get('status', 'UNKNOWN') if isinstance(observed, dict) else None
    if missing or (state is not None and state != 'ACTIVE'):
        reason = ('Current environment is ' + state + '; inventory unavailable'
                  if state is not None and state != 'ACTIVE' else
                  'Incomplete current records: ' + ', '.join(missing))
        return {'status':'BLOCKED', 'reason':reason,
                'classification':{'status':'BLOCKED','reason':reason},
                'conditions':{'reader_complete':False}, 'unknown_fields':missing,
                'current':current, 'environment_status':state or 'UNKNOWN',
                'opening_authorized':False,'movement_authorized':False,
                'source_association_verified':False}
    classification = classify_last_session(**records)
    conditions = {'historical_proof': classification.get('pointer_classification') == CLASS}
    current = current or {}
    conditions.update({
        'fresh_observation': (type(current.get('observed_monotonic')) in (int,float)
                              and 0 <= now-current['observed_monotonic'] <= 3),
        'reader_complete': current.get('complete') is True,
        'no_restrictions': current.get('restriction', 'UNKNOWN') is None,
        'no_guards': current.get('guards') == {},
        'no_other_sessions': current.get('other_sessions') == [],
        'no_host_processes': current.get('host_processes') == [],
        'host_identity_known': bool(current.get('host_boot_id')),
    })
    from .session_precheck import PROTECTED_FAILED_LAYOUT, OPERATIONAL_LAYOUT, FUNCTION_SESSION_LAYOUT
    if (isinstance(records.get('historical_evidence'),dict)
            and records['historical_evidence'].get('layout') in {PROTECTED_FAILED_LAYOUT,OPERATIONAL_LAYOUT,FUNCTION_SESSION_LAYOUT}
            and classification.get('pointer_classification')==CLASS):
        # This archive proves recorded cleanup, not historical resource freshness.
        # Never offer a V2 scope that could not be consumed by its own verifier.
        return {'status':'BLOCKED','conditions':conditions,'classification':classification,
                'scope':None,'scope_sha256':None,'required_review_protocol':'CURRENT_RESOURCE_REVIEW_V1',
                'opening_authorized':False,'movement_authorized':False,'source_association_verified':False}
    # Classification independently checks container processes, boot, environment,
    # descriptor and operation identities. Observation provenance remains a reader duty.
    generic=isinstance(records.get('historical_evidence'),dict) and records['historical_evidence'].get('kind')=='VERIFIED_CLOSURE_ARCHIVE_V2'
    if generic:
        payload={'protocol':'CLOSURE_DISPOSITION_V2','historical':{k:deepcopy(records[k]) for k in
            ('target','start_operation','stop_operation','environment_reference','selection','launch','monitor')},
            'proof':deepcopy(records['historical_evidence'])}
    else:
        payload = deepcopy({k:v for k,v in records.items() if k!='historical_evidence'})
        payload['historical_manifest_sha256'] = FAILED_MANIFEST if records['target']['descriptor']['lifecycle_id']==FAILED_OWNER else HISTORICAL_MANIFEST
        payload['current'] = {k:v for k,v in current.items() if k not in ('observed_monotonic','sources','environment_observation')}
    return {'status':'DRY_RUN_ELIGIBLE' if all(conditions.values()) else 'BLOCKED',
            'conditions':conditions,'unknown_fields':[k for k in (
                'observed_monotonic','complete','restriction','guards','other_sessions',
                'host_processes','host_boot_id') if k not in current],
            'classification':classification, 'scope_sha256':digest(payload),
            'scope':payload,'current_execution_fingerprint':digest({'environment':records.get('environment'),'boot':records.get('inventory',{}).get('boot_id'),'current':{k:v for k,v in current.items() if k not in ('observed_monotonic','sources','environment_observation')}}),'movement_authorized':False,'source_association_verified':False,
            'opening_authorized':False}


def _verified_resource_reader_transition():
    """Bind the one reviewed reader change to exact old/new source bytes."""
    root=Path(__file__).resolve().parents[2]
    legacy=root/'tools/rover_xrce_trace/reader_compat/present_resources_v1.py'
    current=root/RESOURCE_READER_PIN
    try:
        legacy_sha=hashlib.sha256(legacy.read_bytes()).hexdigest()
        current_sha=hashlib.sha256(current.read_bytes()).hexdigest()
    except OSError as exc:
        raise ValueError('Present-resource reader source bytes are unavailable') from exc
    if legacy_sha!=RESOURCE_READER_LEGACY_SHA256 or current_sha!=RESOURCE_READER_CURRENT_SHA256:
        raise ValueError('Present-resource reader source bytes are not the reviewed versions')
    return {'protocol':RESOURCE_READER_SUCCESSOR_PROTOCOL,
            'pin':RESOURCE_READER_PIN,
            'from_sha256':legacy_sha,'to_sha256':current_sha,
            'introduced_by_commit':RESOURCE_READER_INTRODUCER,
            'reason':RESOURCE_READER_REASON,
            'compatibility':'Historical schema /1 and wire schema /2 remain explicitly readable'}


def _successor_link(parent, candidate):
    """Exact transition from the original audit or from the current chain tip.

    Same boot: only the reviewed reader pin may change (V1). New host boot: only
    BOOT_FIELDS may change, bound to that boot; the reader pin may stay or change.
    """
    from uuid import UUID
    audit=parent['audit'];owner=audit['owner_id']
    root=audit.get('schema')=='tfg.diagnostic-disposition/3'
    old={k:v for k,v in audit['scope'].items() if k!='consumer_revision'}
    if (audit.get('schema') not in ('tfg.diagnostic-disposition/3',SUCCESSOR_SCHEMA) or
            audit.get('status')!='DISPOSED_DIAGNOSTICALLY_INCOMPLETE' or
            str(UUID(owner))!=owner or audit['scope_sha256']!=digest(audit['scope']) or
            audit.get('authorization')!=f"AUTHORIZE_DIAGNOSTIC_DISPOSITION {owner} {audit['scope_sha256']}" or
            any(audit.get(k) is not False for k in ('opening_authorized','movement_authorized','source_association_verified')) or
            old.get('protocol')!='CURRENT_RESOURCE_REVIEW_V1' or root==('consumer_revision' in audit['scope']) or
            old['historical']['target']['descriptor']['lifecycle_id']!=owner):
        raise ValueError('Invalid successor predecessor audit/authorization')
    hashes=parent['audit_file_hashes']
    def sha(value):return isinstance(value,str) and len(value)==64 and all(c in '0123456789abcdef' for c in value)
    if set(hashes)!={'intent.json','originals.json'} or not all(sha(v) for v in hashes.values()):
        raise ValueError('Incomplete predecessor byte hashes')
    base={k:v for k,v in candidate.items() if k!='consumer_revision'}
    if set(base)!=set(old):
        raise ValueError('Successor changes scope beyond the permitted reader pin')
    changed={k for k,v in old.items() if base[k]!=v}
    before=old['reader_hashes'];after=base['reader_hashes']
    pins={k for k,v in before.items() if after.get(k)!=v} if isinstance(after,dict) else None
    permitted_pins=set(REVISABLE_PINS)
    if isinstance(pins,set) and RESOURCE_READER_PIN in pins:
        permitted_pins.add(RESOURCE_READER_PIN)
    if (not isinstance(before,dict) or not isinstance(after,dict) or set(before)!=set(after) or
            not isinstance(pins,set) or not pins<=permitted_pins or
            root and before.get(SUCCESSOR_PIN)!=SUCCESSOR_FROM or
            not all(sha(after[k]) for k in pins|{SUCCESSOR_PIN})):
        raise ValueError('Incompatible successor reader versions/pins')
    resource_transition=None
    if RESOURCE_READER_PIN in pins:
        resource_transition=_verified_resource_reader_transition()
        if (before.get(RESOURCE_READER_PIN)!=resource_transition['from_sha256'] or
                after.get(RESOURCE_READER_PIN)!=resource_transition['to_sha256']):
            raise ValueError('Present-resource reader transition hashes differ')
    link={'protocol':(RESOURCE_READER_SUCCESSOR_PROTOCOL if resource_transition else SUCCESSOR_PROTOCOL),
          'owner_id':owner,
          'predecessor_scope_sha256':audit['scope_sha256'],
          'predecessor_authorization':audit['authorization'],
          'audit_file_hashes':hashes,'pin':SUCCESSOR_PIN,
          'before_sha256':before[SUCCESSOR_PIN],'after_sha256':after[SUCCESSOR_PIN]}
    if resource_transition:
        link['reader_transition']=resource_transition
    if pins-{SUCCESSOR_PIN}:
        link['reader_revision']={k:{'before_sha256':before[k],'after_sha256':after[k]} for k in sorted(pins)}
    if 'host_boot_id' not in changed:
        if changed!={'reader_hashes'} or not pins:
            raise ValueError('Successor changes scope beyond the permitted reader pin')
    else:
        if not changed<=set(BOOT_FIELDS):
            raise ValueError('Boot successor changes scope beyond execution context')
        boot=base['host_boot_id'];old_env=old['environment_execution'];env=base['environment_execution']
        old_ctx=old['resource_context'];ctx=base['resource_context']
        if (not isinstance(boot,str) or not boot or not isinstance(env,dict) or not isinstance(ctx,dict) or
                set(env)!=set(old_env)!={'persistent_identity','container_started_at','container_boot_id'} or
                env['persistent_identity']!=old_env['persistent_identity'] or env['container_boot_id']!=boot or
                not isinstance(env['container_started_at'],str) or env['container_started_at']==old_env['container_started_at'] or
                set(ctx)!=set(old_ctx) or ctx.get('boot_id')!=boot or
                any(not isinstance(v,str) or not v for v in ctx.values())):
            raise ValueError('Boot successor identity/execution/context not bound to the new boot')
        if not resource_transition:
            link['protocol']=BOOT_SUCCESSOR_PROTOCOL
        link['boot_transition']={
            'from_host_boot_id':old['host_boot_id'],'to_host_boot_id':boot,
            'from_container_started_at':old_env['container_started_at'],
            'to_container_started_at':env['container_started_at']}
    if 'consumer_revision' in candidate and candidate['consumer_revision']!=link:
        raise ValueError('Successor predecessor link changed')
    return link


def _successor_report(report,current,*,now=None,clock=None):
    if report.get('status')!='DRY_RUN_ELIGIBLE':return report
    try:
        link=_successor_link(current['consumer_predecessor'],report['scope'])
        report['scope']={**report['scope'],'consumer_revision':link}
        report['scope_sha256']=digest(report['scope'])
        report['current_execution_fingerprint']=report['scope_sha256']
        # Include transition validation in the SAME original acquisition window.
        from .present_recovery import host_clock_context
        window=current['host_acquisition'];context=host_clock_context()
        end=(clock or time.monotonic)() if now is None else now
        import math
        ok=(type(end) in (int,float) and math.isfinite(end) and
            context==window['clock_context']==window['received_clock_context'] and
            window['received_monotonic']<=end and 0<=end-window['started_monotonic']<=3)
        report['conditions']['fresh_observation'] &= ok
        report['current_review'].update(assessed_monotonic=end,host_window_s=end-window['started_monotonic'])
        if not report['conditions']['fresh_observation']:
            report.update(status='BLOCKED',reason='Successor review expired or clock context changed')
        return report
    except (KeyError,ValueError,TypeError) as exc:
        return {**report,'status':'BLOCKED','reason':str(exc),'scope':None,'scope_sha256':None}


class OfflineDisposition:
    """Durability/concurrency prototype restricted to /tmp; never touches runtime."""
    def __init__(self, root, *, clock=time.monotonic, write=locks.atomic_json, owner=HISTORICAL_OWNER):
        from uuid import UUID
        if str(UUID(owner))!=owner:raise ValueError('Canonical descriptor owner required')
        self.owner=owner
        self.root=Path(root)
        if self.root.is_symlink() or not self.root.resolve().is_relative_to(Path('/tmp')):
            raise ValueError('Offline sandbox must be below /tmp; real application not implemented')
        self.clock,self.write=clock,write
        self.lock_root=self.root

    def _query_store(self,root):
        """Read-only, including absent state; never completes interrupted intent."""
        if root.is_symlink() or any((root/n).is_symlink() for n in ('intent.json','originals.json','persistence_failed')):
            return {'status':'APPLYING_UNCONFIRMED'}
        if (root/'persistence_failed').exists():return {'status':'APPLYING_UNCONFIRMED'}
        path=root/'intent.json'
        if not path.exists():return {'status':'NOT_ATTEMPTED'}
        try:
            value=json.loads(path.read_bytes())
            if not isinstance(value,dict):raise ValueError('Malformed disposition record')
            if value.get('status') != 'DISPOSED_DIAGNOSTICALLY_INCOMPLETE':
                return {**value,'status':'APPLYING_UNCONFIRMED'}
            if not isinstance(value.get('scope'),dict):raise ValueError('Malformed disposition scope')
            if value['scope_sha256']!=digest(value['scope']):raise ValueError('Scope corrupt')
            if (value.get('owner_id')!=self.owner or
                value.get('authorization')!=f"AUTHORIZE_DIAGNOSTIC_DISPOSITION {self.owner} {value['scope_sha256']}" or
                any(value.get(k) is not False for k in ('movement_authorized','source_association_verified','opening_authorized'))):
                raise ValueError('Disposition scope/flags/authorization contradictory')
            if value.get('schema')=='tfg.diagnostic-disposition/2':verified_closure_archive(value['scope']['proof'])
            if value.get('schema')=='tfg.diagnostic-disposition/3':
                from .present_recovery import BASIS
                from .session_precheck import recorded_cleanup_archive
                if value['scope'].get('protocol')!=BASIS or recorded_cleanup_archive(value['scope']['proof'])['historical']!=value['scope']['historical']:
                    raise ValueError('Present review original/scope changed')
            archive=json.loads((root/'originals.json').read_bytes())
            if archive!=value['scope']:raise ValueError('Archive changed')
            return value
        except (OSError,ValueError,KeyError,TypeError):return {'status':'APPLYING_UNCONFIRMED'}

    def predecessor_binding(self,*,verified_original=None):
        # Internal reuse of an already verified read. Re-read/hash the exact
        # bytes and compare them; do not repeat the full historical archive read.
        original=self._query_store(self.root) if verified_original is None else verified_original
        if original.get('status')!='DISPOSED_DIAGNOSTICALLY_INCOMPLETE':
            raise ValueError('Predecessor not durably complete')
        return self._binding(self.root,original)

    def _binding(self,root,record):
        raw={n:(root/n).read_bytes() for n in ('intent.json','originals.json')}
        if json.loads(raw['intent.json'])!=record or json.loads(raw['originals.json'])!=record['scope']:
            raise ValueError('Predecessor changed while binding bytes')
        return {'audit':record,'audit_file_hashes':{n:hashlib.sha256(v).hexdigest() for n,v in raw.items()}}

    def record_binding(self,record):
        """Byte binding of the original audit or of one stored successor."""
        if record.get('schema')!=SUCCESSOR_SCHEMA:
            return self.predecessor_binding(verified_original=record)
        return self._binding(self.root/'revisions'/record['scope_sha256'],record)

    def chain_bindings(self,prior=None):
        """(tip, predecessor of tip) of the verified chain; (original, None) without successors."""
        prior=self.query() if prior is None else prior
        if prior.get('status')!='DISPOSED_DIAGNOSTICALLY_INCOMPLETE':
            raise ValueError('Predecessor not durably complete')
        original={k:v for k,v in prior.items() if k not in ('consumer_successor','consumer_chain')}
        records=[original,*prior.get('consumer_chain',[])]
        return self.record_binding(records[-1]),(self.record_binding(records[-2]) if len(records)>1 else None)

    def query(self):
        original=self._query_store(self.root);revisions=self.root/'revisions'
        if not os.path.lexists(revisions):return original
        try:
            if original.get('status')!='DISPOSED_DIAGNOSTICALLY_INCOMPLETE' or revisions.is_symlink():
                raise ValueError('Unknown predecessor/revision directory')
            children=list(revisions.iterdir())
            if not children:raise ValueError('Missing or ambiguous successor')
            by_parent={}
            for path in children:
                if (path.is_symlink() or not path.is_dir() or len(path.name)!=64 or
                        any(c not in '0123456789abcdef' for c in path.name)):
                    raise ValueError('Unsafe successor path')
                successor=self._query_store(path)
                if (successor.get('status')!='DISPOSED_DIAGNOSTICALLY_INCOMPLETE' or
                        successor.get('schema')!=SUCCESSOR_SCHEMA or successor['scope_sha256']!=path.name or
                        type(successor.get('offline_only')) is not bool or
                        successor['offline_only'] is not original.get('offline_only')):
                    raise ValueError('Partial/contradictory successor')
                observations=successor.get('application_observations')
                if not isinstance(observations,list) or len(observations)!=2:
                    raise ValueError('Successor lacks two original revalidations')
                for observation in observations:
                    if not isinstance(observation,dict):raise ValueError('Malformed successor observation')
                    duration=observation.get('host_window_s')
                    conditions=observation.get('current_conditions',{})
                    if (type(duration) not in (int,float) or not 0<=duration<=3 or
                            not isinstance(conditions,dict) or not isinstance(observation.get('resources'),dict) or
                            set(conditions)!=set(successor['scope']['reviewed_outcome']['required_conditions']) or
                            not all(v is True for v in conditions.values()) or
                            observation['resources'].get('reader_hashes')!=successor['scope']['reader_hashes']):
                        raise ValueError('Successor revalidation changed/incomplete')
                if 'consumer_revision' not in successor['scope']:raise ValueError('Missing predecessor link')
                parent_sha=successor['scope']['consumer_revision'].get('predecessor_scope_sha256')
                if parent_sha in by_parent:raise ValueError('Ambiguous successor fork')
                by_parent[parent_sha]=successor
            # One linear chain from the untouched original; every link re-verified
            # against its predecessor's current bytes. Forks/orphans fail closed.
            chain=[];parent=self.predecessor_binding(verified_original=original)
            while parent['audit']['scope_sha256'] in by_parent:
                successor=by_parent.pop(parent['audit']['scope_sha256'])
                _successor_link(parent,successor['scope'])
                chain.append(successor);parent=self.record_binding(successor)
            if by_parent or not chain:raise ValueError('Orphan successor outside the chain')
            return {**original,'consumer_successor':chain[-1],'consumer_chain':chain}
        except (OSError,KeyError,TypeError,ValueError):
            return {'status':'APPLYING_UNCONFIRMED','reason':'Successor incomplete, altered or ambiguous; no fallback'}

    def apply_successor(self,records,reader,*,scope_sha256,authorization):
        """Same locks/two reads/persistence; one new linked successor on the chain tip."""
        if authorization!=f'AUTHORIZE_DIAGNOSTIC_DISPOSITION {self.owner} {scope_sha256}':
            raise ValueError('Exact new successor scope authorization required')
        with ExitStack() as stack:
            for name in ('v1.execution.lock','registry.lock'):
                stack.enter_context(locks.file_mutex(self.lock_root/name,blocking=False))
            prior=self.query()
            if prior.get('status')!='DISPOSED_DIAGNOSTICALLY_INCOMPLETE':
                raise ValueError('Successor predecessor/prior intent uncertain; no replay')
            chain=prior.get('consumer_chain',[])
            if any(s['scope_sha256']==scope_sha256 for s in chain):
                if chain[-1]['scope_sha256']==scope_sha256:return chain[-1]  # completed repeat: query only
                raise ValueError('Superseded successor already applied; no replay')
            parent,_=self.chain_bindings(prior)
            reports=[]
            for _ in range(2):
                current=reader()
                if self.record_binding(parent['audit'])!=parent:
                    raise ValueError('Predecessor changed during revalidation')
                current={**current,'consumer_predecessor':parent}
                report=dry_run(records,current,clock=self.clock)
                if (report.get('status')!='DRY_RUN_ELIGIBLE' or report.get('scope_sha256')!=scope_sha256 or
                        report['scope']['consumer_revision']['owner_id']!=self.owner):
                    raise ValueError('Successor scope changed or current observation invalid')
                reports.append(report)
            if reports[0]['scope']!=reports[1]['scope']:raise ValueError('Successor changed during inspection')
            intent={'schema':SUCCESSOR_SCHEMA,'status':'APPLYING','owner_id':self.owner,
                    'scope_sha256':scope_sha256,'scope':reports[0]['scope'],'authorization':authorization,
                    'movement_authorized':False,'source_association_verified':False,'opening_authorized':False,
                    'offline_only':getattr(self,'offline_only',True),
                    'application_observations':[v['current_review'] for v in reports]}
            revisions=self.root/'revisions'
            # Exclusive for the first successor; later ones extend the verified chain.
            # The per-scope directory is always exclusive: an interrupted one blocks replay.
            if not chain:revisions.mkdir(mode=0o700)
            path=revisions/scope_sha256;path.mkdir(mode=0o700)
            for directory in (self.root,revisions):
                fd=os.open(directory,os.O_RDONLY|os.O_DIRECTORY)
                try:os.fsync(fd)
                finally:os.close(fd)
            self._persist(path,intent)
            result=self.query()
            if result.get('status')!='DISPOSED_DIAGNOSTICALLY_INCOMPLETE':
                raise ValueError('Successor persistence uncertain; query only')
            return result['consumer_successor']

    def apply(self, records, reader, *, scope_sha256, authorization):
        """Sandbox only; reader invoked under same lock ORDER as protected lifecycle.

        No retry after partial intent. Completed repeats are query-only and do not
        mean that current opening eligibility or identity remains valid.
        """
        expected=f'AUTHORIZE_DIAGNOSTIC_DISPOSITION {self.owner} {scope_sha256}'
        if authorization!=expected:raise ValueError('Exact scope authorization required')
        self.root.mkdir(mode=0o700,parents=True,exist_ok=True)
        with ExitStack() as stack:
            for name in ('v1.execution.lock','registry.lock'):
                stack.enter_context(locks.file_mutex(self.lock_root/name,blocking=False))
            prior=self.query()
            if prior['status']!='NOT_ATTEMPTED':
                if (prior['status']=='DISPOSED_DIAGNOSTICALLY_INCOMPLETE'
                        and prior.get('scope_sha256')==scope_sha256):return prior
                raise ValueError('Prior incompatible or interrupted intent; inspect, never replay')
            first=dry_run(records,reader(),clock=self.clock)
            if (first['status']!='DRY_RUN_ELIGIBLE' or first['scope_sha256']!=scope_sha256
                    or records['target']['descriptor']['lifecycle_id']!=self.owner):
                raise ValueError('Scope changed or observation unknown')
            second=dry_run(records,reader(),clock=self.clock)
            if (second['status']!='DRY_RUN_ELIGIBLE' or second['scope_sha256']!=scope_sha256 or
                    first['scope'].get('protocol') in {'CLOSURE_DISPOSITION_V2','CURRENT_RESOURCE_REVIEW_V1'} and first['current_execution_fingerprint']!=second['current_execution_fingerprint']):
                raise ValueError('Changed during inspection')
            intent={'schema':('tfg.diagnostic-disposition/3' if first['scope'].get('protocol')=='CURRENT_RESOURCE_REVIEW_V1' else 'tfg.diagnostic-disposition/2' if first['scope'].get('protocol')=='CLOSURE_DISPOSITION_V2' else 'tfg.diagnostic-disposition/1'),'status':'APPLYING',
                    'owner_id':self.owner,'scope_sha256':scope_sha256,
                    'scope':first['scope'],'authorization':authorization,
                    'movement_authorized':False,'source_association_verified':False,
                    'opening_authorized':False,'offline_only':getattr(self,'offline_only',True)}
            if intent['schema']=='tfg.diagnostic-disposition/3':
                intent['application_observations']=[first['current_review'],second['current_review']]
            self._persist(self.root,intent)
            return self.query()

    def _persist(self,root,intent):
        # Exclusive durable claim precedes all other persistence. Its existence
        # blocks replay even if subsequent archive/atomic-json/fsync fails.
        fd=os.open(root/'intent.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        try:
            with os.fdopen(fd,'w') as stream:
                json.dump(intent,stream,allow_nan=False);stream.flush();os.fsync(stream.fileno())
            parent=os.open(root,os.O_RDONLY|os.O_DIRECTORY)
            try:os.fsync(parent)
            finally:os.close(parent)
            self.write(root/'originals.json',intent['scope'])
            self.write(root/'intent.json',{**intent,'status':'DISPOSED_DIAGNOSTICALLY_INCOMPLETE'})
        except BaseException:
            try:
                with (root/'persistence_failed').open('x') as failure:
                    failure.write('Persistence outcome uncertain; inspect only\n')
                    failure.flush();os.fsync(failure.fileno())
            except OSError:
                pass
            # Never infer completion from a lost/failed final persistence.
            # Claim remains auditable; caller must query, never resubmit.
            raise




def historical_records(directory):
    """Read real archived records only. Current observations intentionally UNKNOWN."""
    root=Path(directory)
    def read(name):return json.loads((root/name).read_bytes())
    if (root/'post-close-host-state.json').is_file():
        target=read('post-close-host-state.json')['target'];pointer=target['descriptor']
        prefix='container-copies'+pointer['prefix']+'/'
        return dict(target=target,start_operation=read('runtime-copies/start/operation.json'),
            stop_operation=read('runtime-copies/stop/operation.json'),
            environment_reference=read('runtime-copies/start/rover_environment_reference.json'),
            environment={'status':'ACTIVE',**pointer['manifest'],**read('runtime-copies/start/rover_environment_reference.json')['environment'],
                'state':read('container-after.stdout')['state']},historical_evidence=root,
            selection=read(prefix+'selection.json'),launch=read(prefix+'launch.json'),
            monitor=read(prefix+'capture/monitor.json'),inventory=read('post-close-index.json')['inventory'])
    target=read('host_state_after.json')['target'];pointer=target['descriptor']
    prefix='container_after/container_copies'+pointer['prefix']+'/'
    # Supply saved inventory ONLY to assess historical proof, never as current eligibility.
    from .session_precheck import POINTER
    records=dict(target=target,start_operation=read('runtime_copies/start/operation.json'),
        stop_operation=read('runtime_copies/stop/operation.json'),
        environment_reference=read('runtime_copies/start/rover_environment_reference.json'),
        environment=read('environment_after.json'),historical_evidence=root,
        selection=read(prefix+'selection.json'),launch=read(prefix+'launch.json'),
        monitor=read(prefix+'capture/monitor.json'),inventory=dict(owned=[],ambiguous=[],agents=[],
            boot_id=read(prefix+'capture/monitor.json')['monitor']['boot_id'],
            state_files={POINTER:json.dumps({**pointer,'status':'BLOCKED',
                'movement_authorized':False,'source_association_verified':False})}))
    return records


def historical_dry_run(directory):
    # Empty inventory is a historical proof scenario, not a live observation.
    report=dry_run(historical_records(directory))
    report['inventory_basis']='HISTORICAL_PROOF_SCENARIO_NOT_CURRENT_READ'
    return report


EVIDENCE = locks.PROJECT_ROOT/'simulation/ros2_gazebo/results/rover_xrce_trial_2026_10_24/b9ee5ec5-049d-47cc-b22f-26535b972b5f'


def current_records(context=None, *, present=False):
    """Bounded current metadata using lifecycle environment/ownership implementations.

    No starts, signals, ROS or services. Caller must hold project exclusion.
    Container Python runs only public read-only supervisor functions from supplied
    repository source; installed /tmp helpers are not trusted or modified.
    """
    import subprocess
    from tools.reconciliation_environment import inspect_environment,inspect_review_environment
    from .present_recovery import host_clock_context,HOST_WINDOW
    host_domain=host_clock_context()
    started=time.monotonic();sources=[]
    if context is None:context={}
    context.update(started_at_utc=locks.utc_now(),sources=sources)
    def source(name):
        item={'source':name,'read_at_utc':locks.utc_now()}
        if present:item['read_monotonic']=time.monotonic()
        sources.append(item)
    def read(path):
        source(str(path));return json.loads(path.read_bytes())
    target=read(locks.LOCK_ROOT.parent/'diagnostic_agent_session.json')
    owner=target['descriptor']['lifecycle_id'];closing=target['closed_by']
    from uuid import UUID
    if str(UUID(owner))!=owner or str(UUID(closing))!=closing:raise ValueError('Unknown lifecycle/closing owner')
    reference=read(locks.LOCK_ROOT.parent/'simulation_lifecycle'/owner/'rover_environment_reference.json')
    prior=ProjectDisposition(owner).query()
    proof=prior.get('scope',{}).get('proof') if prior.get('schema') in {'tfg.diagnostic-disposition/2','tfg.diagnostic-disposition/3'} and prior.get('status')=='DISPOSED_DIAGNOSTICALLY_INCOMPLETE' else None
    records={'target':target,'start_operation':read(locks.LOCK_ROOT.parent/'simulation_lifecycle'/owner/'operation.json'),
        'stop_operation':read(locks.LOCK_ROOT.parent/'simulation_lifecycle'/closing/'operation.json'),
        'environment_reference':reference,'historical_evidence':(locks.PROJECT_ROOT/'simulation/ros2_gazebo/results/rover_xrce_trial_2026_10_25/0f678646-fe41-47b0-ba33-20fad1ae873e' if owner==FAILED_OWNER else EVIDENCE)}
    if proof is not None:records['historical_evidence']=proof
    present=present or (prior.get('schema')=='tfg.diagnostic-disposition/3' and proof is not None)
    if present:records['recovery_basis']='CURRENT_RESOURCE_REVIEW_V1'
    environment=(inspect_review_environment() if present else inspect_environment())
    context['environment']=environment;source('reconciliation_environment.inspect_environment')
    current={'complete':False,'sources':sources,'environment_observation':environment,
             'observed_monotonic':started}
    if environment.get('status')!='ACTIVE':
        return records,current
    # Never enter a replacement container merely because its name matches.
    expected=target['descriptor']['manifest']
    if any(environment.get(k)!=expected.get(k) for k in ('engine_id','container_id','image_id')):
        raise ValueError('Environment identity mismatch; no container inventory')
    records['environment']={k:environment[k] for k in ('status','engine_id','container_id','image_id','name','created_at','state')}
    prefix=target['descriptor']['prefix']
    if prefix!='/tmp/tfg_diagnostic_agents/'+owner:raise ValueError('Unexpected overlay')
    files=[prefix+'/'+n for n in ('selection.json','launch.json','capture/monitor.json')]
    # Same definitions as protected shutdown; no CLI start/stop invocation.
    code="""import sys,json,types,os
from pathlib import Path
v=json.load(sys.stdin)
p=types.ModuleType('tfg_simulation_profiles');sys.modules[p.__name__]=p
exec(v['profiles'],p.__dict__)
m=types.ModuleType('readonly_disposition_supervisor');sys.modules[m.__name__]=m
exec(v['supervisor'],m.__dict__)
def query_context():
    return {'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
            **{k+'_namespace':os.readlink('/proc/self/ns/'+k) for k in ('net','pid','time')}}
before=query_context() if v.get('present') else None
result=m.readonly_inventory(v['files'])
if v.get('present'):
    sys.path.insert(0,'/workspace/tfg')
    from tools.rover_xrce_trace import present_resources as r,present_recovery as recovery
    from pathlib import Path
    if recovery.reader_hashes()!=v['reader_hashes']:raise ValueError('Recovery reader changed before query')
    scope=r.scope(v['host_launch'],r.read_config())
    result['resources']=r.collect(scope,known_processes={(p['pid'],p['start_ticks']) for p in result['owned']})
    result['resources']['reader_hashes']=recovery.reader_hashes()
    if result['resources']['reader_hashes']!=v['reader_hashes']:raise ValueError('Recovery reader changed during query')
    result['query_context_before']=before;result['query_context_after']=query_context()
    if (before!=result['query_context_after'] or result['boot_id']!=before['boot_id'] or
            (result['resources'].get('context') is not None and {k:result['resources']['context'][k] for k in before}!=before)):
        raise ValueError('SDK query process/namespace/boot context changed')
print(json.dumps(result))
"""
    supervisor=locks.PROJECT_ROOT/'simulation/ros2_gazebo/scripts/sim_processes.py'
    profiles=locks.PROJECT_ROOT/'tools/simulation_profiles.py'
    payload={'profiles':profiles.read_text(),'supervisor':supervisor.read_text(),'files':files}
    if present:
        from .present_recovery import reader_hashes
        payload.update(present=True,reader_hashes=reader_hashes(),host_launch=(locks.PROJECT_ROOT/'simulation/ros2_gazebo/launch/tfg_demo.launch.py').read_text())
    context['inventory_source_sha256']=digest(payload)
    result=subprocess.run(['docker','exec','-i',environment['container_id'],'python3','-B','-c',code],
        input=json.dumps(payload),capture_output=True,text=True,timeout=8,check=False)
    context['inventory_return_code']=result.returncode
    source('sim_processes.readonly_inventory in exact container')
    if result.returncode:
        context['inventory_stderr']=result.stderr[-4096:]
        raise ValueError('Container inventory query failed; not absence: '+result.stderr[-512:])
    inventory=json.loads(result.stdout);records['inventory']=inventory
    from tools.reconciliation_environment import active_execution_identity, read_container_boot_id
    execution=active_execution_identity(environment,inventory.get('boot_id'))
    # Bind the proc sample to a stable CURRENT execution, not the historical one.
    if present:
        before=inventory.get('query_context_before');after_context=inventory.get('query_context_after')
        if not isinstance(before,dict) or before!=after_context or before.get('boot_id')!=inventory.get('boot_id'):
            raise ValueError('SDK boot/namespace recheck absent or changed')
        rechecked_boot=after_context['boot_id']
        after=inspect_review_environment(final=True)
    else:
        rechecked_boot=read_container_boot_id(environment)
        after=inspect_environment()
    context['environment_recheck']=after
    source('reconciliation_environment metadata/boot recheck after inventory')
    if active_execution_identity(after,rechecked_boot)!=execution:
        raise ValueError('Current container execution changed during inventory')
    context['current_environment_execution']=execution
    for field,name in [('selection','selection.json'),('launch','launch.json'),('monitor','capture/monitor.json')]:
        records[field]=json.loads(inventory['files'][prefix+'/'+name])
    host=[]
    roles={'tools.virtual_preflight_worker','tools.preflight_sequence_worker','tools.simulation_lifecycle',
           'tools.simulation_mission_executor','tools.rover_ground_executor','tools.rover_identity_worker'}
    for path in Path('/proc').iterdir():
        if not path.name.isdigit() or int(path.name)==os.getpid():continue
        try:
            args=(path/'cmdline').read_bytes().split(b'\0')
            if roles.intersection(a.decode(errors='replace') for a in args):
                host.append(locks.process_identity(int(path.name)))
        except (FileNotFoundError,ProcessLookupError):continue
    source('host /proc relevant role inventory; vehicle_execution_lock.process_identity')
    guards={p.name:digest(json.loads(p.read_bytes())) for p in locks.LOCK_ROOT.glob('*.json')}
    source('vehicle_locks/*.json and vehicle_execution_lock.restriction')
    current.update(restriction=locks.restriction(),guards=guards,host_processes=host,
        host_boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
        other_sessions=[] if inventory.get('state_files',{}).keys()=={'/tmp/tfg_demo.diagnostic.json'} else ['unknown-or-extra-state'],
        complete=True,observed_monotonic=started)
    if present:
        current.update(resources=inventory['resources'],host_time_namespace=os.readlink('/proc/self/ns/time'),
            disposition_state=prior.get('status'),disposition_schema=prior.get('schema'))
    if present:
        received_domain=host_clock_context()
        current['host_acquisition']={'basis':HOST_WINDOW,'started_monotonic':started,
            'received_monotonic':time.monotonic(),'clock_context':host_domain,
            'received_clock_context':received_domain}
        context['host_acquisition']=current['host_acquisition']
    if prior.get('consumer_successor') is not None:
        # The precheck re-derives the tip's own link, so it needs the tip's predecessor.
        current['consumer_predecessor']=ProjectDisposition(owner).chain_bindings(prior)[1]
    return records,current


def _real_dry_run_locked(evidence=None, *, present=False, successor_owner=None):
    """One current observation under existing locks; no durable state written."""
    context={}
    with ExitStack() as stack:
        for name in ('v1.execution.lock','registry.lock'):
            # Require existing lock files; do not create coordination state.
            import fcntl
            fd=os.open(locks.LOCK_ROOT/name,os.O_RDONLY|os.O_NOFOLLOW)
            stack.callback(os.close,fd);fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:
            records,current=current_records(context,present=True) if present else current_records(context)
            if evidence is not None:records['historical_evidence']=closure_archive_reference(evidence)
            if successor_owner is not None:
                if records['target']['descriptor']['lifecycle_id']!=successor_owner:
                    raise ValueError('Successor target/owner changed')
                store=ProjectDisposition(successor_owner);prior=store.query()
                if prior.get('status')!='DISPOSED_DIAGNOSTICALLY_INCOMPLETE':
                    raise ValueError('Predecessor is uncertain; query only')
                current['consumer_predecessor']=store.chain_bindings(prior)[0]  # review the next link on the tip
            result=dry_run(records,current)
            result['current_sources']=current.get('sources',[])
            if present:result['observation_context']=context
            return result
        except TypeError:
            raise  # Programming/contract errors must not masquerade as normal blocking.
        except Exception as exc:
            return {'status':'BLOCKED','reason':str(exc),'error_type':type(exc).__name__,
                    'observation_context':context,'opening_authorized':False}


def real_dry_run(evidence=None, *, present=False, successor_owner=None):
    try:
        return _real_dry_run_locked(evidence,present=present,successor_owner=successor_owner)
    except (OSError, ValueError, locks.VehicleBusy) as exc:
        return {'status':'BLOCKED','reason':'Coordination unavailable: '+str(exc),
                'error_type':type(exc).__name__,'opening_authorized':False}


class ProjectDisposition(OfflineDisposition):
    """Explicit project audit application. No descriptor/guard mutation or start.

    Authorization is a recorded declaration, not authenticated human identity.
    No arbitrary root/reader arguments are exposed in the production entry point.
    """
    def __init__(self,owner=HISTORICAL_OWNER):
        from uuid import UUID
        if str(UUID(owner))!=owner:raise ValueError('Canonical descriptor owner required')
        self.owner=owner
        self.root=locks.LOCK_ROOT.parent/'historical_dispositions'/owner
        self.lock_root=locks.LOCK_ROOT
        if self.root.is_symlink() or self.root.parent.is_symlink():raise ValueError('Unsafe disposition destination')
        self.clock,self.write=time.monotonic,locks.atomic_json
        self.offline_only=False

    def apply_reviewed(self, *, scope_sha256, authorization, evidence=None, present=False):
        records={}
        def reader():
            fresh,current=current_records(present=True) if present else current_records();records.clear();records.update(fresh)
            if evidence is not None:records['historical_evidence']=closure_archive_reference(evidence)
            # The declaration binds stable facts, not timestamps/source observation metadata.
            return current if fresh.get('recovery_basis') else {k:v for k,v in current.items() if k not in ('sources','environment_observation')}
        return super().apply(records,reader,scope_sha256=scope_sha256,authorization=authorization)

    def apply_successor_reviewed(self,*,scope_sha256,authorization,evidence=None):
        records={}
        def reader():
            fresh,current=current_records(present=True);records.clear();records.update(fresh)
            if evidence is not None:records['historical_evidence']=closure_archive_reference(evidence)
            return current
        return super().apply_successor(records,reader,scope_sha256=scope_sha256,authorization=authorization)



def assess_disposition(records, current, audit, *, now=None):
    """Pure future-precheck consumption. Never reuses historical process eligibility.

    Must receive query() output plus freshly collected records under shared locks.
    Returns no start/movement authorization, and does not mutate base classification.
    """
    return _assess_disposition_report(records,current,audit,dry_run(records,current,now=now),now=now)


def _assess_disposition_report(records,current,audit,report,*,now=None):
    """Consume this call's verified report, never a caller-supplied acceptance.

    Scope equality remains exact. Avoid rereading the archive/rebuilding the
    same scope, but check age/context after audit comparisons as well. No new
    observation or transfer timestamp replaces the original acquisition time.
    """
    owner=records['target']['descriptor']['lifecycle_id'];successor_valid=True
    has_successor='consumer_successor' in audit
    if has_successor:
        original=audit;successor=audit['consumer_successor']
        try:
            parent=current['consumer_predecessor']
            chain=audit.get('consumer_chain',[successor])
            expected=(chain[-2] if len(chain)>1 else
                      {k:v for k,v in original.items() if k not in ('consumer_successor','consumer_chain')})
            if chain[-1]!=successor or parent['audit']!=expected:
                raise ValueError('Predecessor audit association changed')
            _successor_link(parent,successor['scope'])
            if (successor.get('schema')!=SUCCESSOR_SCHEMA or 'consumer_revision' not in successor['scope'] or
                    successor.get('offline_only') is not original.get('offline_only')):
                raise ValueError('Unknown successor protocol/context')
            audit=successor
        except (KeyError,ValueError,TypeError):
            successor_valid=False;audit={}
    checks={'audit_completed':audit.get('status')=='DISPOSED_DIAGNOSTICALLY_INCOMPLETE',
            'same_descriptor':audit.get('owner_id')==owner,
            'scope_digest_matches':bool(report.get('scope_sha256')) and audit.get('scope_sha256')==report.get('scope_sha256'),
            'scope_matches':bool(report.get('scope')) and audit.get('scope')==report.get('scope'),
            'authorization_matches':bool(report.get('scope_sha256')) and
                audit.get('authorization')==f"AUTHORIZE_DIAGNOSTIC_DISPOSITION {owner} {report.get('scope_sha256')}",
            'authority_flags_preserved':all(audit.get(k) is False for k in
                ('movement_authorized','source_association_verified','opening_authorized'))}
    if has_successor:checks['successor_link_valid']=successor_valid
    if report.get('status')=='DRY_RUN_ELIGIBLE':
        end=time.monotonic() if now is None else now
        import math
        finite=type(end) in (int,float) and math.isfinite(end)
        observed=current.get('observed_monotonic')
        fresh=finite and type(observed) in (int,float) and math.isfinite(observed) and 0<=end-observed<=3
        if records.get('recovery_basis')=='CURRENT_RESOURCE_REVIEW_V1':
            from .present_recovery import host_clock_context
            window=current['host_acquisition']
            context_ok=host_clock_context()==window['clock_context']==window['received_clock_context']
            report['conditions']['host_window_complete'] &= context_ok
            fresh=fresh and report['conditions']['host_window_complete']
            report['current_review']['consumed_monotonic']=end
        report['conditions']['fresh_observation'] &= fresh
        if not report['conditions']['fresh_observation']:
            report.update(status='BLOCKED',reason='Disposition consumption observation expired or clock context changed')
    checks['current_assessment_valid']=report.get('status')=='DRY_RUN_ELIGIBLE'
    valid=all(checks.values())
    audit_scope=audit.get('scope') if isinstance(audit.get('scope'),dict) else {}
    return {'status':'BLOCKED','historical_pointer_resolved':valid,
            'diagnostic_capture':'INCOMPLETE','movement_authorized':False,
            'source_association_verified':False,'opening_authorized':False,
            'reason':'Separate opening authorization/admission required' if valid else
                     'Disposition/current checks absent, stale, changed or contradictory',
            'current_assessment':report,'checks':checks,
            'scope_changed_fields':sorted(k for k in set(audit_scope)|set(report.get('scope') or {})
                if audit_scope.get(k)!=(report.get('scope') or {}).get(k))}



REVIEWED_SCOPE = 'de67fb09603f1df8fb72c9e9bbba1f9d43f184dbe1af1f66dd16b547ee1b3ee8'


def diagnostic_precheck(records, current, audit, *, now=None):
    """Pure diagnostic decision, never generic BLOCKED->CLEAR or start consent.

    Legacy dispositions retain their reviewed scope. V2 requires a manifest-bound
    independent closure archive and an exact descriptor/scope declaration; fresh
    current checks are always separate. Neither protocol grants a start.
    """
    report=dry_run(records,current,now=now)
    if report.get('reason'):
        return {**report,'precheck_satisfied':False,'disposition_consumed':False}
    classification=report['classification']
    assessment=None
    recognized=(audit.get('schema') in {'tfg.diagnostic-disposition/2','tfg.diagnostic-disposition/3'} or
                audit.get('scope_sha256')==REVIEWED_SCOPE or records['target']['descriptor']['lifecycle_id']==FAILED_OWNER)
    if recognized and audit.get('offline_only') is False:
        assessment=_assess_disposition_report(records,current,audit,report,now=now)
    disposed=assessment is not None and assessment['historical_pointer_resolved']
    current_ok=all(value for key,value in report['conditions'].items() if key!='historical_proof')
    complete=classification.get('status')=='CLEAR' and current_ok
    satisfied=complete or disposed
    review_required=(classification.get('pointer_classification')==CLASS and current_ok and not disposed)
    return {'status':'SATISFIED' if satisfied else 'BLOCKED',
            'precheck_satisfied':bool(satisfied),'historical_classification':classification,
            'disposition_consumed':bool(disposed),'conditions':report['conditions'],
            'disposition_checks':assessment['checks'] if assessment else {},
            'scope_changed_fields':assessment['scope_changed_fields'] if assessment else [],
            'disposition_assessment_reason':assessment['current_assessment'].get('reason') if assessment else None,
            'reason':'Current diagnostic precheck passed; separate start authorization required'
                     if satisfied else 'Historical diagnostics incomplete; separate scope review required'
                     if review_required else 'Historical disposition or current checks invalid/unknown/changed',
            'opening_authorized':False,'movement_authorized':False,
            'source_association_verified':False}


def diagnostic_precheck_locked(*, expected_target=None, evidence=None):
    """Caller holds execution+registry exclusion; never reacquire (no deadlock).

    Lifecycle invokes before any lease/state/backend changes. Standalone CLI below
    holds the same locks only for observation, so its result is never a start token.
    """
    context={}
    try:
        records,current=current_records(context)
        if evidence is not None:records['historical_evidence']=closure_archive_reference(evidence)
        if expected_target is not None and records.get('target')!=expected_target:
            raise ValueError('Diagnostic target changed during admission')
        owner=records.get('target',{}).get('descriptor',{}).get('lifecycle_id')
        if not isinstance(owner,str):return diagnostic_precheck(records,current,{},now=time.monotonic())
        audit=ProjectDisposition(owner).query()
        result=diagnostic_precheck(records,current,audit)
        result['sources']=current.get('sources',[])
        result['audit_state']=audit.get('status','UNKNOWN')
        result['current_environment_execution']=context.get('current_environment_execution')
        if evidence is not None:result['closure_evidence_reference']=records['historical_evidence']
        return result
    except TypeError:
        raise  # Do not hide a programming defect behind a successful query response.
    except Exception as exc:
        return {'status':'BLOCKED','precheck_satisfied':False,'reason':str(exc),
                'observation_context':context,'opening_authorized':False,
                'movement_authorized':False,'source_association_verified':False}


def current_diagnostic_precheck(evidence=None):
    from contextlib import ExitStack
    import fcntl
    try:
        with ExitStack() as stack:
            for name in ('v1.execution.lock','registry.lock'):
                fd=os.open(locks.LOCK_ROOT/name,os.O_RDONLY|os.O_NOFOLLOW)
                stack.callback(os.close,fd);fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            return diagnostic_precheck_locked(evidence=evidence) if evidence is not None else diagnostic_precheck_locked()
    except (OSError,ValueError,locks.VehicleBusy) as exc:
        return {'status':'BLOCKED','precheck_satisfied':False,'reason':'Coordination unavailable: '+str(exc),
                'opening_authorized':False,'movement_authorized':False,'source_association_verified':False}


if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser(description='Historical disposition; no simulation controls')
    parser.add_argument('action',choices=['dry-run','dry-run-current','dry-run-present','dry-run-successor',
        'apply-present-reviewed','apply-successor-reviewed','apply-reviewed','diagnostic-precheck','query'])
    parser.add_argument('--owner',default=HISTORICAL_OWNER)
    parser.add_argument('--evidence')
    parser.add_argument('--scope-sha256')
    parser.add_argument('--authorization')
    args=parser.parse_args()
    if args.action=='diagnostic-precheck':result=current_diagnostic_precheck(args.evidence) if args.evidence is not None else current_diagnostic_precheck()
    elif args.action=='query':result=ProjectDisposition(args.owner).query()
    elif args.action=='dry-run-present':result=real_dry_run(args.evidence,present=True)
    elif args.action=='dry-run-successor':result=real_dry_run(args.evidence,present=True,successor_owner=args.owner)
    elif args.action=='apply-successor-reviewed':
        result=ProjectDisposition(args.owner).apply_successor_reviewed(scope_sha256=args.scope_sha256,authorization=args.authorization,evidence=args.evidence)
    elif args.action=='apply-present-reviewed':
        result=ProjectDisposition(args.owner).apply_reviewed(scope_sha256=args.scope_sha256,authorization=args.authorization,evidence=args.evidence,present=True)
    elif args.action=='dry-run-current':result=real_dry_run(args.evidence)
    elif args.action=='apply-reviewed':
        result=ProjectDisposition(args.owner).apply_reviewed(scope_sha256=args.scope_sha256,authorization=args.authorization,evidence=args.evidence)
    else:result=historical_dry_run(args.evidence)
    print(json.dumps(result,indent=2,allow_nan=False))
