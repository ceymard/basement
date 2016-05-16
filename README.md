# Basement

A dead-simple solution to backup all volumes of a container and to restore them.

It assumes that all the backups of a given host will reside in a local directory ready to be rsync'd somewhere else (like S3 or GCS.)

Archives always have names like `bs_yyyy-mm@HH.MM.SS`, and the automatic prune command only applies on names starting with `bs_` to allow for durable custom backups.

# Why

While volume drivers certainly seem nice, I wanted a simpler and less involved solution to back up my containers. I also happen to like the relative simplicity and encapsulation of having volumes that I don't have to explicitely bind to have my applications working.

Which is why I wanted a tool that would allow me to type `myutil backup my-container` to have it backed up somewhere and `myutil restore my-container from-my-backup` to have all of its volumes completely restored to what I backuped earlier.

Being able to have multiple save points back in time and easily restore to whichever I chose was a big plus, which attic filled with relative grace.

# Run

You will need the basement docker image :

```sh
docker pull ceymard/basement
```

To run basement, it is recommanded to create a small script in `/usr/local/bin`. An example is provided in the `example` folder. The script must bind `/var/run/docker.sock` and `/repositories` to respectively the docker socket and a directory where the repositories will be stored.

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

NOTE: this is not implemented yet.

# Not stopping a container

By default when backuping or restoring a running container, basement will shut it down, __along with any container using the same mount points__. To prevent such behaviour, use the `--no-stop` flag on the command line.

This behaviour exists for safely backuping databases which usually require to be stopped to avoid data loss because of data not commited to the disk yet.

# Using a backup name

By default, a repository name is inferred from the container's name to which its id is appended (this is to avoid mixing up containers inadvertently.)

To specify another name, pass `--backup-name <the name>` on the command line to any command. This can also be used to restore another container from any backup.

You can also specify the name in the `basement.backup-name` label.

# Prefixes

By default, basement creates archives with the name `bs_<timestamp>`. All of the prune operations use this prefix to avoid messing up with custom archive names or custom prefixes you may use.

You can always override the prefix by passing `--prefix <my_prefix>` to any command, or setting `basement.prefix=...` in a container label.

# Pruning content

There are three ways you can prune unneeded archives ;

```bash
# By passing arguments that attic prune accept in a string
basement prune <container> '-d 3 -w 4'

# By passing the prune arguments to backup
basement backup <container> --prune '-d 3 -w 4'

# Or by settings the label 'basement.auto-prune=<prune options>'
basement backup <container> # Backup will then apply the auto prune
```

`--prefix` affects all of these commands. Remember that by default, `--prefix` is set to `"bs"`.

# Encryption

Basement can currently only use passphrases, which you can set with `--passphrase` on any operation, or through the `basement.passphrase` label.

# Labels

Basement supports the following labels :

* `basement.backup-name` as the repository name
* `basement.prefix` as the default prefix for this container
* `basement.auto-prune` as the prune options to apply **everytime** `backup` is called
* `basement.passphrase` as the passphrase to give to the backups
