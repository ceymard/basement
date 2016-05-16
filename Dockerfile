FROM ceymard/borg:latest

ADD scripts /basement

ENTRYPOINT ["/basement/run.py"]
