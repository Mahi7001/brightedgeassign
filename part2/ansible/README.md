# Part 2 – Ansible Deployment

## Overview

This part implements an Ansible role for deploying the `data-sync` service on
CentOS/Rocky 8 service hosts.

The deployment follows a standard Ansible role structure and separates
configuration, tasks, handlers, and the systemd service template.

## Directory Structure

```text
part2/
└── ansible/
    ├── ansible.cfg
    ├── requirements.yml
    ├── group_vars/
    │   └── service.yml
    ├── playbooks/
    │   └── playbook-data-sync.yml
    └── roles/
        └── be-data-sync/
            ├── defaults/
            │   └── main.yml
            ├── handlers/
            │   └── main.yml
            ├── tasks/
            │   └── main.yml
            └── templates/
                └── data-sync.service.j2
```

## Ansible Role

The role is named:

```text
be-data-sync
```

The role is responsible for:

* Installing Python 3.9 and pip using `yum`.
* Cloning or updating the `data-sync` Git repository.
* Deploying the application under `/srv/data-sync`.
* Creating a Python virtual environment under `/srv/data-sync/venv`.
* Installing Python dependencies into the virtual environment.
* Deploying the systemd service using a Jinja2 template.
* Configuring the application using Ansible variables.
* Ensuring the systemd service is enabled and running.
* Restarting the service when its configuration changes.
* Restricting execution of the role to hosts where `be_role` is set to
  `service`.

## Configuration

Service-specific variables are defined in:

```text
ansible/group_vars/service.yml
```

The following variables are configured:

```yaml
data_sync_app_env
data_sync_redis_host
data_sync_log_level
```

These values are passed to the systemd service as:

```text
APP_ENV
REDIS_HOST
LOG_LEVEL
```

Role defaults are maintained in:

```text
ansible/roles/be-data-sync/defaults/main.yml
```

This keeps environment-specific configuration separate from the role logic.

## Playbook

The deployment playbook is:

```text
ansible/playbooks/playbook-data-sync.yml
```

The playbook targets the:

```text
service
```

host group and applies the:

```text
be-data-sync
```

role.

The role supports the following tags:

```text
install
deploy
```

### Install tasks

Run only installation-related tasks:

```bash
ansible-playbook playbooks/playbook-data-sync.yml --tags install
```

### Deploy tasks

Run deployment-related tasks:

```bash
ansible-playbook playbooks/playbook-data-sync.yml --tags deploy
```

### Full deployment

Run the complete playbook:

```bash
ansible-playbook playbooks/playbook-data-sync.yml
```

## Role Execution Guard

The role verifies that it is being executed only on service hosts.

The host must have:

```yaml
be_role: service
```

If the condition is not satisfied, the role fails rather than deploying the
service to an unintended host.

## Systemd Service

The systemd unit is generated from:

```text
ansible/roles/be-data-sync/templates/data-sync.service.j2
```

The template receives the application configuration from Ansible variables
and creates the service unit for `data-sync`.

A handler is used to restart the service when the systemd configuration
changes.

## Validation

### Syntax Check

Validate the playbook syntax:

```bash
ansible-playbook playbooks/playbook-data-sync.yml --syntax-check
```

### Ansible Lint

Run `ansible-lint` against the playbook:

```bash
ansible-lint playbooks/playbook-data-sync.yml
```

### Inventory

Verify the configured inventory and the `service` group:

```bash
ansible-inventory --graph
```

The inventory should contain the target hosts under:

```text
service
```

## Deployment Verification

After deployment, verify the systemd service:

```bash
systemctl status data-sync
```

Verify that the service is enabled:

```bash
systemctl is-enabled data-sync
```

Verify that the service is running:

```bash
systemctl is-active data-sync
```

## Files

| File                                                | Purpose                       |
| --------------------------------------------------- | ----------------------------- |
| `ansible.cfg`                                       | Ansible configuration         |
| `requirements.yml`                                  | Ansible dependency definition |
| `group_vars/service.yml`                            | Service host configuration    |
| `playbooks/playbook-data-sync.yml`                  | Deployment playbook           |
| `roles/be-data-sync/defaults/main.yml`              | Role default variables        |
| `roles/be-data-sync/tasks/main.yml`                 | Deployment tasks              |
| `roles/be-data-sync/handlers/main.yml`              | Service restart handler       |
| `roles/be-data-sync/templates/data-sync.service.j2` | Systemd unit template         |

## Assignment Requirements Covered

The implementation covers the required Part 2 functionality:

* Standard Ansible role structure.
* Python 3.9 and pip installation.
* Data-sync repository deployment to `/srv/data-sync`.
* Python virtual environment at `/srv/data-sync/venv`.
* Python dependency installation.
* Jinja2-based systemd unit.
* `APP_ENV`, `REDIS_HOST`, and `LOG_LEVEL` configuration.
* Enabled and running systemd service.
* Restart handler for configuration changes.
* `be_role == 'service'` execution restriction.
* Deployment through the `service` host group.
* `install` and `deploy` tags.
* Ansible-lint validation.

The implementation is intended to remain focused on the requirements of the
Part 2 assignment without adding unrelated infrastructure or deployment
components.
