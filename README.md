# Basement

A dead-simple solution to backup all volumes of a container and to restore them.

It assumes that all the backups of a given host will reside in a local directory ready to be rsync'd somewhere else (like S3 or GCS.)

Archives always have names like `bs_yyyy-mm@HH.MM.SS`, and the automatic prune command only applies on names starting with `bs_` to allow for durable custom backups.

# TODO

* Handle all options (prefix, stop-shared) on command line as well as in labels
* stop all containers (basement.stop-shared --stop-shared)
* backup all (on label basement.auto-backup=true)
* auto-prune and prune command
* backup regularity ? (cron ?)

Nice to have
* Report generation !


# Run

To run basement, it is recommanded to create a small script in `/usr/local/bin`. An example is provided in the `example` folder.

From this point on, it will be assumed that such a script is installed on your system as `basement`.

## Backup a single container

```sh
basement backup <container-name>
```

## Restore a single container

```sh
basement restore <container-name> <archive-name>
```

## List all archives names for a given container

```sh
basement list <container-name>
```

## Backup all tagged containers

When specifying `auto-backup=true` in a container label, it will be backed up everytime basement is called with `backup-all`

```bash
basement backup-all
```

# How it does it

When launching the basement image, it re-launches itself immediately with the target container's volumes mounted in `/backup`, from where it starts attic 
to backup or restore data.
