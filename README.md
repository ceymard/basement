# Basement

A dead-simple solution to backup all volumes of a container and to restore them. It can also optionally help to keep track of all the backups of a system, along with their containers and can send mails once done.

It assumes that all the backups of a give host will reside in a directory ready to be rsync'd somewhere else (like S3 or GCS.)

Archives always have names like `bs-yyyy-mm-dd-HH-MM`, and the automatic prune command only applies on names starting with `bs-` to allow for durable custom backups.

The `ATTIC_PRUNE` environment variable contains further options to be passed to `attic`, and is set by default to `--keep-daily 14 --keep-weekly 4 --keep-monthly 2 --prefix bs-`.

# Run

## Backup a single container

```sh
docker run --rm -it -v '/path/to/all/repositories:/repositories' -v '/var/run/docker.sock:/var/run/docker.sock' ceymard/basement backup <container-name>
```

Example :

```sh
docker run --rm -it -v '/home/me/backups:/repositories' -v '/var/run/docker.sock:/var/run/docker.sock' ceymard/basement backup mynicecontainer
```

## Restore a single container

```sh
docker run --rm -it -v '/path/to/all/repositories:/repositories' -v '/var/run/docker.sock:/var/run/docker.sock' ceymard/basement restore <container-name> [<backup-name>::]<archive-name>
```

Example :

```sh
docker run --rm -it -v '/home/me/backups:/repositories' -v '/var/run/docker.sock:/var/run/docker.sock' ceymard/basement restore mycontainer bs-2016-05-13-04-03
```

The backup name can be omitted since we keep track of it, but if you're trying to restore a backup of another container into a new one, you may need to provide it.

# Backup a list of container

To make the automation via cron (or any other script) easier and the output more readable, it is easier to specify a file.

```
my_container
another_container: --keep-weekly 2
*hot_backup_container
```


# How it does it

When launching the basement image, it re-launches itself immediately with the target container's volumes mounted in `/volumes`, from where it starts attic 
to backup or restore data.

# Container protection

???