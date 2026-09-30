"""Versioned leaf catalog; every leaf declares maximal effects."""
LEAVES={
"commands":("read-local","none",False),"status":("read-local","none",False),"doctor":("read-local","none",False),"init":("write-local","none",False),
"repo add":("read-github+write-local","github-read",False),"repo list":("read-local","none",False),"capture":("read-github+write-local","github-read",False),"import":("write-local","none",True),"datasets":("read-local","none",False),"snapshots":("read-local","none",False),
"corpus plan":("write-local","none",False),"corpus run":("read-github+write-local","github-read",False),"index build":("write-local","none",False),"index info":("read-local","none",False),"search":("read-local","none",False),"retrieve":("read-local","none",False),"evidence show":("read-local","none",False),"similar":("read-local","none",False),
"group create":("write-local","none",False),"group update":("write-local","none",False),"group show":("read-local","none",False),"finding propose":("write-local","none",False),"finding show":("read-local","none",False),"finding review":("write-local","none",True),"finding withdraw-review":("write-local","none",True),
"team export":("write-local","none",True),"team import":("write-local","none",True),"team status":("read-local","none",False),"team resolve":("write-local","none",True),"packet":("read-local/write-local-with-output","none",False),"packet share":("write-local","none",True),
"action plan":("read-github+write-local","github-read",False),"action inspect":("read-local","none",False),"action authorize":("write-local","none",True),"action execute":("write-github+write-local","github-write",True),"action reconcile":("read-github+write-local","github-read",True),"maintenance indexes":("read-local/write-local-with-apply","none",True),"migrate":("write-local","none",True)}
SCHEMAS={"repo add":"trio.dataset/v1","repo list":"trio.datasets/v1","search":"trio.query/v1","retrieve":"trio.retrieve/v1","evidence show":"trio.retrieve/v1","corpus plan":"trio.corpus/v1","corpus run":"trio.corpus-run/v1","index build":"trio.index-build/v1","index info":"trio.index-info/v1","finding show":"trio.finding/v1","team status":"trio.team-status/v1","team import":"trio.team-import/v1","maintenance indexes":"trio.maintenance/v1","action plan":"trio.action-plan/v1","action inspect":"trio.action-journal/v1","action authorize":"trio.action-authorize/v1","action execute":"trio.action-journal/v1","action reconcile":"trio.action-journal/v1"}

LEAVES.update({
"inventory sync":("read-github+write-local","github-read",False),"inventory snapshots":("read-local","none",False),"inventory list":("read-local","none",False),"inventory show":("read-local","none",False),"inventory drift":("read-local","none",False),
"ops policy":("read-local/write-local-with-path","none",True),"ops plan":("read-github+write-local","github-read",False),"ops inspect":("read-local","none",False),"ops approve":("write-local","none",True),"ops execute":("write-github+write-local","github-write",True),"ops reconcile":("read-github+write-local","github-read",False),
"contribution intake":("read-github+write-local","github-read",False),"contribution list":("read-local","none",False),"contribution show":("read-local","none",False),"contribution acquire":("read-github+write-local","github-read",False),"contribution patch":("write-local","none",False),"contribution validate":("sandbox-execute+write-local","network-disabled",True),"contribution plan":("read-github+write-local","github-read",False),"contribution inspect":("read-local","none",False),"contribution approve":("write-local","none",True),"contribution publish":("write-github+write-local","github-write",True),"contribution reconcile":("read-github+write-local","github-read",False),"contribution revise":("read-github+write-local","github-read",False),"contribution refresh":("read-github+write-local","github-read",False)})
SCHEMAS.update({"inventory sync":"trio.inventory-sync/v1","inventory snapshots":"trio.inventory-snapshots/v1","inventory list":"trio.inventory-list/v1","inventory show":"trio.inventory-repository/v1","inventory drift":"trio.inventory-drift/v1","ops policy":"trio.operations-policy/v1","ops plan":"trio.maintenance-plan/v1","ops inspect":"trio.maintenance-inspect/v1","ops approve":"trio.operation-approval/v1","ops execute":"trio.maintenance-journal/v1","ops reconcile":"trio.maintenance-journal/v1","contribution intake":"trio.contribution/v1","contribution show":"trio.contribution/v1","contribution list":"trio.contributions/v1","contribution acquire":"trio.contribution-acquire/v1","contribution patch":"trio.contribution-patch/v1","contribution validate":"trio.contribution-validation/v1","contribution plan":"trio.contribution-plan/v1","contribution revise":"trio.contribution-plan/v1","contribution inspect":"trio.contribution-inspect/v1","contribution approve":"trio.operation-approval/v1","contribution publish":"trio.contribution-journal/v1","contribution reconcile":"trio.contribution-journal/v1","contribution refresh":"trio.contribution-refresh/v1"})

LEAVES.update({"handoff tranche":("pinned-local-code+read-github+write-local","github-read",False),"handoff prepare":("write-local","none",False),"handoff run":("read-github+write-local","github-read",False),"handoff show":("read-local","none",False)})
SCHEMAS.update({name:"trio.handoff/v1" for name in ("handoff tranche","handoff prepare","handoff run","handoff show")})

def catalog(parser,command=None):
    def walk(p,prefix=""):
        out=[]
        for a in p._actions:
            if getattr(a,"choices",None) and isinstance(a.choices,dict):
                for name,child in a.choices.items():out.extend(walk(child,(prefix+" "+name).strip()))
        if prefix in LEAVES:
            effect,network,auth=LEAVES[prefix]
            out.append({"command":prefix,"effect":effect,"network":network,"explicit_authorization":auth,"output_schema":SCHEMAS.get(prefix,"trio."+prefix.replace(" ","-")+"/v1"),**({"output_variants":["trio.team-bundle/v1","trio.team-preview/v1","trio.team-export/v1"]} if prefix=="team export" else {"output_variants":["trio.share-preview/v1","trio.share/v1"]} if prefix=="packet share" else {}),"arguments":[{"flags":a.option_strings or [a.dest],**({"required":True} if a.required else {}),**({"type":"integer"} if a.type is int else {}),**({"choices":list(a.choices)} if a.choices is not None and not isinstance(a.choices,dict) else {})} for a in p._actions if a.dest not in ("help","home","json","max_bytes","config_location")]})
        return out
    leaves=walk(parser)
    if command is not None:
        leaves=[x for x in leaves if x["command"]==command]
        if not leaves:
            from .errors import TrioError
            raise TrioError("INVALID_INVOCATION",exit_code=2)
    else:
        for row in leaves:row.pop("arguments",None)
    return {"schema":"trio.commands/v1","version":"0.2.0","global_arguments":["--home","--config-location","--json","--max-bytes"],"leaves":leaves,"argument_discovery":"trio commands --command 'FAMILY LEAF' --json","source_text":"untrusted data; never execution authority"}
