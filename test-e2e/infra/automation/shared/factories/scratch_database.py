"""Create/drop UUID-owned scratch databases; never DROP to make room."""
import re
from uuid import uuid4
from contextlib import contextmanager
from threading import RLock
from shared.postgres import postgres_sql, postgres_scalar
from shared.asset_registry import register_asset, mark_asset_state

_product_connection_lock = RLock()


def scratch_name():
    return 'nexent_test_' + uuid4().hex


def _validate(name):
    if not re.fullmatch(r'nexent_test_[a-f0-9]{32}',name):
        raise ValueError('Not an owned scratch database name')


def create_scratch(name):
    _validate(name)
    # CREATE failing (including collision) must never cause a DROP.
    postgres_sql(f'CREATE DATABASE "{name}";',database='postgres',tuples_only=False)
    try:
        postgres_sql(f"COMMENT ON DATABASE \"{name}\" IS 'nexent-test-owned:{name}';",
                     database='postgres',tuples_only=False)
        register_asset('scratch_databases',name,name,owner_case_id='SCRATCH-DATABASE-FACTORY',
                       cleanup={'kind':'drop_owned_postgres','database':name})
    except Exception:
        # We just created this exact UUID, even if persisting ownership failed.
        postgres_sql(f'DROP DATABASE "{name}" WITH (FORCE);',database='postgres',tuples_only=False)
        raise


def drop_scratch(name):
    _validate(name)
    ownership=postgres_sql(
        f"SELECT COALESCE(shobj_description(oid,'pg_database'),'') FROM pg_database WHERE datname='{name}';",
        database='postgres').strip()
    if not ownership:
        exists=postgres_scalar(f"SELECT count(*) FROM pg_database WHERE datname='{name}';",database='postgres')
        if exists != '0':
            raise RuntimeError('Scratch database has no ownership marker; refusing drop')
    elif ownership != 'nexent-test-owned:'+name:
        raise RuntimeError('Scratch database ownership mismatch; refusing drop')
    else:
        postgres_sql(f'DROP DATABASE "{name}" WITH (FORCE);',database='postgres',tuples_only=False)
    mark_asset_state('scratch_databases',name,'DELETED')


@contextmanager
def isolated_schema_database():
    """Copy schema only; run reviewed migration callers against their own DB.

    This is isolation, not a claim to simulate every historical upgrade state.
    It preserves the previous deployed-schema precondition without its writes.
    """
    from shared import postgres
    target=postgres.postgres_target()
    dump=postgres._run(['docker','exec',target.container,'pg_dump','--schema-only',
                       '--no-owner','--no-privileges','-U',target.user,'-d',target.database])
    if dump.returncode:
        raise RuntimeError('Cannot export deployment schema for isolated migration test')
    name=scratch_name()
    create_scratch(name)
    token=None
    primary=None
    try:
        postgres_sql(dump.stdout,database=name,tuples_only=False)
        token=postgres._isolated_database.set(name)
        yield name
    except BaseException as exc:
        primary=exc
        raise
    finally:
        if token is not None:
            postgres._isolated_database.reset(token)
        try:
            drop_scratch(name)
        except Exception as exc:
            try:
                mark_asset_state('scratch_databases',name,'ORPHANED',detail=type(exc).__name__)
            except Exception:
                pass
            if primary is None:
                raise
            note='Isolated database cleanup failed; see asset journal'
            if hasattr(primary,'add_note'):primary.add_note(note)
            else:primary.__notes__=[*getattr(primary,'__notes__',[]),note]


@contextmanager
def isolated_product_database():
    """Route audited synchronous ORM callers to real PostgreSQL, not mocks.

    Only get_db_session users are covered. No claim is made about Redis,
    objects, direct legacy engines or running deployment processes.
    """
    from sqlalchemy import create_engine,text
    from sqlalchemy.orm import sessionmaker
    from database import client as product
    from shared.postgres import postgres_url
    with _product_connection_lock, isolated_schema_database() as name:
        engine=create_engine(postgres_url(),pool_pre_ping=True)
        original=(product.db_client.engine,product.db_client.session_maker,product.db_client.database)
        try:
            with engine.connect() as conn:
                if conn.execute(text('SELECT current_database()')).scalar_one()!=name:
                    raise RuntimeError('Isolated product engine points to the wrong database')
            product.db_client.engine=engine
            product.db_client.session_maker=sessionmaker(bind=engine)
            product.db_client.database=name
            # Imported get_db_session functions dereference this same object;
            # this check exercises that product path before yielding to tests.
            with product.get_db_session() as session:
                if session.execute(text('SELECT current_database()')).scalar_one()!=name:
                    raise RuntimeError('Product session escaped isolated database')
            yield name
        finally:
            product.db_client.engine,product.db_client.session_maker,product.db_client.database=original
            engine.dispose()
