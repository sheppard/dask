from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import os

import numpy as np
import pandas as pd
import pandas.util.testing as tm
import pytest

import dask
import dask.multiprocessing
import dask.dataframe as dd
from dask.dataframe.utils import assert_eq

try:
    import fastparquet
except ImportError:
    fastparquet = False

try:
    import pyarrow.parquet as pq
except ImportError:
    pq = False

df = pd.DataFrame({'x': [6, 2, 3, 4, 5],
                   'y': [1.0, 2.0, 1.0, 2.0, 1.0]},
                  index=pd.Index([10, 20, 30, 40, 50], name='myindex'))

ddf = dd.from_pandas(df, npartitions=3)


@pytest.fixture(params=[pytest.mark.skipif(not fastparquet, 'fastparquet',
                                           reason='fastparquet not found'),
                        pytest.mark.skipif(not pq, 'pyarrow',
                                           reason='pyarrow not found')])
def engine(request):
    return request.param


def check_fastparquet():
    if not fastparquet:
        pytest.skip('fastparquet not found')


def check_pyarrow():
    if not pq:
        pytest.skip('pyarrow not found')


def write_read_engines(xfail_arrow_to_fastparquet=True):
    if xfail_arrow_to_fastparquet:
        xfail = (pytest.mark.xfail(reason="Can't read arrow directories with fastparquet"),)
    else:
        xfail = ()
    ff = () if fastparquet else (pytest.mark.skip(reason='fastparquet not found'),)
    aa = () if pq else (pytest.mark.skip(reason='pyarrow not found'),)
    engines = [pytest.param('fastparquet', 'fastparquet', marks=ff),
               pytest.param('pyarrow', 'pyarrow', marks=aa),
               pytest.param('fastparquet', 'pyarrow', marks=ff + aa),
               pytest.param('pyarrow', 'fastparquet', marks=ff + aa + xfail)]
    return pytest.mark.parametrize(('write_engine', 'read_engine'), engines)


write_read_engines_xfail = write_read_engines(xfail_arrow_to_fastparquet=True)


@write_read_engines_xfail
def test_local(tmpdir, write_engine, read_engine):
    tmp = str(tmpdir)
    data = pd.DataFrame({'i32': np.arange(1000, dtype=np.int32),
                         'i64': np.arange(1000, dtype=np.int64),
                         'f': np.arange(1000, dtype=np.float64),
                         'bhello': np.random.choice(['hello', 'yo', 'people'], size=1000).astype("O")})
    df = dd.from_pandas(data, chunksize=500)

    df.to_parquet(tmp, write_index=False, engine=write_engine)

    files = os.listdir(tmp)
    assert '_common_metadata' in files
    assert 'part.0.parquet' in files

    df2 = dd.read_parquet(tmp, index=False, engine=read_engine)

    assert len(df2.divisions) > 1

    out = df2.compute(get=dask.get).reset_index()

    for column in df.columns:
        assert (data[column] == out[column]).all()


@write_read_engines_xfail
def test_index(tmpdir, write_engine, read_engine):
    fn = str(tmpdir)
    ddf.to_parquet(fn, engine=write_engine)
    ddf2 = dd.read_parquet(fn, engine=read_engine)
    assert_eq(df, ddf2)


@pytest.mark.parametrize('index', [False, True])
@write_read_engines_xfail
def test_empty(tmpdir, write_engine, read_engine, index):
    fn = str(tmpdir)
    df = pd.DataFrame({'a': ['a', 'b', 'b'], 'b': [4, 5, 6]})[:0]
    if index:
        df.set_index('a', inplace=True, drop=True)
    ddf = dd.from_pandas(df, npartitions=2)

    ddf.to_parquet(fn, write_index=index, engine=write_engine)
    read_df = dd.read_parquet(fn, engine=read_engine)
    assert_eq(df, read_df)


@write_read_engines(xfail_arrow_to_fastparquet=False)
def test_read_glob(tmpdir, write_engine, read_engine):
    fn = str(tmpdir)
    ddf.to_parquet(fn, engine=write_engine)
    if os.path.exists(os.path.join(fn, '_metadata')):
        os.unlink(os.path.join(fn, '_metadata'))

    files = os.listdir(fn)
    assert '_metadata' not in files

    ddf2 = dd.read_parquet(os.path.join(fn, '*'), engine=read_engine)
    assert_eq(df, ddf2)


@write_read_engines_xfail
def test_auto_add_index(tmpdir, write_engine, read_engine):
    fn = str(tmpdir)
    ddf.to_parquet(fn, engine=write_engine)
    ddf2 = dd.read_parquet(fn, columns=['x'], index='myindex', engine=read_engine)
    assert_eq(df[['x']], ddf2)


@write_read_engines_xfail
def test_index_column_false_index(tmpdir, write_engine, read_engine):
    fn = str(tmpdir)
    ddf.to_parquet(fn, engine=write_engine)
    ddf2 = dd.read_parquet(fn, columns=['myindex'], index=False, engine=read_engine)
    assert_eq(pd.DataFrame(df.index), ddf2, check_index=False)


@pytest.mark.parametrize("columns", [['myindex'], []])
@pytest.mark.parametrize("index", ['myindex', None])
@write_read_engines_xfail
def test_columns_index(tmpdir, write_engine, read_engine, columns, index):
    fn = str(tmpdir)
    ddf.to_parquet(fn, engine=write_engine)
    ddf2 = dd.read_parquet(fn, columns=columns, index=index, engine=read_engine)
    assert_eq(df[[]], ddf2)


@write_read_engines_xfail
def test_no_index(tmpdir, write_engine, read_engine):
    fn = str(tmpdir)
    df = pd.DataFrame({'a': [1, 2, 3], 'b': [4, 5, 6]})
    ddf = dd.from_pandas(df, npartitions=2)
    ddf.to_parquet(fn, write_index=False, engine=write_engine)
    ddf2 = dd.read_parquet(fn, engine=read_engine)
    assert_eq(df, ddf2, check_index=False)


def test_read_series(tmpdir, engine):
    fn = str(tmpdir)
    ddf.to_parquet(fn, engine=engine)
    ddf2 = dd.read_parquet(fn, columns=['x'], engine=engine)
    assert_eq(df[['x']], ddf2)

    ddf2 = dd.read_parquet(fn, columns='x', index='myindex', engine=engine)
    assert_eq(df.x, ddf2)


def test_names(tmpdir, engine):
    fn = str(tmpdir)
    ddf.to_parquet(fn, engine=engine)

    def read(fn, **kwargs):
        return dd.read_parquet(fn, engine=engine, **kwargs)

    assert (set(read(fn).dask) == set(read(fn).dask))

    assert (set(read(fn).dask) !=
            set(read(fn, columns=['x']).dask))

    assert (set(read(fn, columns=('x',)).dask) ==
            set(read(fn, columns=['x']).dask))


@pytest.mark.parametrize('c', [['x'], 'x', ['x', 'y'], []])
def test_optimize(tmpdir, c):
    check_fastparquet()
    fn = str(tmpdir)
    ddf.to_parquet(fn)
    ddf2 = dd.read_parquet(fn)
    assert_eq(df[c], ddf2[c])
    x = ddf2[c]

    dsk = x.__dask_optimize__(x.dask, x.__dask_keys__())
    assert len(dsk) == x.npartitions
    assert all(v[4] == c for v in dsk.values())


@pytest.mark.skipif(not hasattr(pd.DataFrame, 'to_parquet'),
                    reason="no to_parquet method")
@write_read_engines(False)
def test_roundtrip_from_pandas(tmpdir, write_engine, read_engine):
    fn = str(tmpdir.join('test.parquet'))
    df = pd.DataFrame({'x': [1, 2, 3]})
    df.to_parquet(fn, engine=write_engine)
    ddf = dd.read_parquet(fn, engine=read_engine)
    assert_eq(df, ddf)


def test_categorical(tmpdir):
    check_fastparquet()
    tmp = str(tmpdir)
    df = pd.DataFrame({'x': ['a', 'b', 'c'] * 100}, dtype='category')
    ddf = dd.from_pandas(df, npartitions=3)
    dd.to_parquet(ddf, tmp)

    ddf2 = dd.read_parquet(tmp, categories=['x'])
    assert ddf2.compute().x.cat.categories.tolist() == ['a', 'b', 'c']

    # autocat
    ddf2 = dd.read_parquet(tmp)
    assert ddf2.compute().x.cat.categories.tolist() == ['a', 'b', 'c']

    ddf2.loc[:1000].compute()
    df.index.name = 'index'  # defaults to 'index' in this case
    assert assert_eq(df, ddf2)

    # dereference cats
    ddf2 = dd.read_parquet(tmp, categories=[])

    ddf2.loc[:1000].compute()
    assert (df.x == ddf2.x).all()


def test_append(tmpdir, engine):
    """Test that appended parquet equal to the original one."""
    check_fastparquet()
    tmp = str(tmpdir)
    df = pd.DataFrame({'i32': np.arange(1000, dtype=np.int32),
                       'i64': np.arange(1000, dtype=np.int64),
                       'f': np.arange(1000, dtype=np.float64),
                       'bhello': np.random.choice(['hello', 'yo', 'people'],
                                                  size=1000).astype("O")})
    df.index.name = 'index'

    half = len(df) // 2
    ddf1 = dd.from_pandas(df.iloc[:half], chunksize=100)
    ddf2 = dd.from_pandas(df.iloc[half:], chunksize=100)
    ddf1.to_parquet(tmp)
    ddf2.to_parquet(tmp, append=True)

    ddf3 = dd.read_parquet(tmp, engine=engine)
    assert_eq(df, ddf3)


def test_append_with_partition(tmpdir):
    check_fastparquet()
    tmp = str(tmpdir)
    df0 = pd.DataFrame({'lat': np.arange(0, 10), 'lon': np.arange(10, 20),
                        'value': np.arange(100, 110)})
    df0.index.name = 'index'
    df1 = pd.DataFrame({'lat': np.arange(10, 20), 'lon': np.arange(10, 20),
                        'value': np.arange(120, 130)})
    df1.index.name = 'index'
    dd_df0 = dd.from_pandas(df0, npartitions=1)
    dd_df1 = dd.from_pandas(df1, npartitions=1)
    dd.to_parquet(dd_df0, tmp, partition_on=['lon'])
    dd.to_parquet(dd_df1, tmp, partition_on=['lon'], append=True,
                  ignore_divisions=True)

    out = dd.read_parquet(tmp).compute()
    out['lon'] = out.lon.astype('int64')  # just to pass assert
    # sort required since partitioning breaks index order
    assert_eq(out.sort_values('value'), pd.concat([df0, df1])[out.columns],
              check_index=False)


def test_append_wo_index(tmpdir):
    """Test append with write_index=False."""
    check_fastparquet()
    tmp = str(tmpdir.join('tmp1.parquet'))
    df = pd.DataFrame({'i32': np.arange(1000, dtype=np.int32),
                       'i64': np.arange(1000, dtype=np.int64),
                       'f': np.arange(1000, dtype=np.float64),
                       'bhello': np.random.choice(['hello', 'yo', 'people'],
                                                  size=1000).astype("O")})
    half = len(df) // 2
    ddf1 = dd.from_pandas(df.iloc[:half], chunksize=100)
    ddf2 = dd.from_pandas(df.iloc[half:], chunksize=100)
    ddf1.to_parquet(tmp)

    with pytest.raises(ValueError) as excinfo:
        ddf2.to_parquet(tmp, write_index=False, append=True)
    assert 'Appended columns' in str(excinfo.value)

    tmp = str(tmpdir.join('tmp2.parquet'))
    ddf1.to_parquet(tmp, write_index=False)
    ddf2.to_parquet(tmp, write_index=False, append=True)

    ddf3 = dd.read_parquet(tmp, index='f')
    assert_eq(df.set_index('f'), ddf3)


def test_append_overlapping_divisions(tmpdir):
    """Test raising of error when divisions overlapping."""
    check_fastparquet()
    tmp = str(tmpdir)
    df = pd.DataFrame({'i32': np.arange(1000, dtype=np.int32),
                       'i64': np.arange(1000, dtype=np.int64),
                       'f': np.arange(1000, dtype=np.float64),
                       'bhello': np.random.choice(['hello', 'yo', 'people'],
                                                  size=1000).astype("O")})
    half = len(df) // 2
    ddf1 = dd.from_pandas(df.iloc[:half], chunksize=100)
    ddf2 = dd.from_pandas(df.iloc[half - 10:], chunksize=100)
    ddf1.to_parquet(tmp)

    with pytest.raises(ValueError) as excinfo:
        ddf2.to_parquet(tmp, append=True)
    assert 'Appended divisions' in str(excinfo.value)

    ddf2.to_parquet(tmp, append=True, ignore_divisions=True)


def test_append_different_columns(tmpdir):
    """Test raising of error when non equal columns."""
    check_fastparquet()
    tmp = str(tmpdir)
    df1 = pd.DataFrame({'i32': np.arange(100, dtype=np.int32)})
    df2 = pd.DataFrame({'i64': np.arange(100, dtype=np.int64)})
    df3 = pd.DataFrame({'i32': np.arange(100, dtype=np.int64)})

    ddf1 = dd.from_pandas(df1, chunksize=2)
    ddf2 = dd.from_pandas(df2, chunksize=2)
    ddf3 = dd.from_pandas(df3, chunksize=2)

    ddf1.to_parquet(tmp)

    with pytest.raises(ValueError) as excinfo:
        ddf2.to_parquet(tmp, append=True)
    assert 'Appended columns' in str(excinfo.value)

    with pytest.raises(ValueError) as excinfo:
        ddf3.to_parquet(tmp, append=True)
    assert 'Appended dtypes' in str(excinfo.value)


def test_ordering(tmpdir):
    check_fastparquet()
    tmp = str(tmpdir)
    df = pd.DataFrame({'a': [1, 2, 3],
                       'b': [10, 20, 30],
                       'c': [100, 200, 300]},
                      index=pd.Index([-1, -2, -3], name='myindex'),
                      columns=['c', 'a', 'b'])
    ddf = dd.from_pandas(df, npartitions=2)
    dd.to_parquet(ddf, tmp)

    pf = fastparquet.ParquetFile(tmp)
    assert pf.columns == ['myindex', 'c', 'a', 'b']

    ddf2 = dd.read_parquet(tmp, index='myindex')
    assert_eq(ddf, ddf2)


def test_read_parquet_custom_columns(tmpdir, engine):
    tmp = str(tmpdir)
    data = pd.DataFrame({'i32': np.arange(1000, dtype=np.int32),
                         'f': np.arange(1000, dtype=np.float64)})
    df = dd.from_pandas(data, chunksize=50)
    df.to_parquet(tmp)

    df2 = dd.read_parquet(tmp, columns=['i32', 'f'], engine=engine)
    assert_eq(df2, df2, check_index=False)

    df3 = dd.read_parquet(tmp, columns=['f', 'i32'], engine=engine)
    assert_eq(df3, df3, check_index=False)


@pytest.mark.parametrize('df,write_kwargs,read_kwargs', [
    (pd.DataFrame({'x': [3, 2, 1]}), {}, {}),
    (pd.DataFrame({'x': ['c', 'a', 'b']}), {'object_encoding': 'utf8'}, {}),
    (pd.DataFrame({'x': ['cc', 'a', 'bbb']}), {'object_encoding': 'utf8'}, {}),
    (pd.DataFrame({'x': [b'a', b'b', b'c']}), {'object_encoding': 'bytes'}, {}),
    (pd.DataFrame({'x': pd.Categorical(['a', 'b', 'a'])}),
     {'object_encoding': 'utf8'}, {'categories': ['x']}),
    (pd.DataFrame({'x': pd.Categorical([1, 2, 1])}), {}, {'categories': ['x']}),
    (pd.DataFrame({'x': list(map(pd.Timestamp, [3000, 2000, 1000]))}), {}, {}),
    (pd.DataFrame({'x': [3000, 2000, 1000]}).astype('M8[ns]'), {}, {}),
    pytest.mark.xfail((pd.DataFrame({'x': [3, 2, 1]}).astype('M8[ns]'), {}, {}),
                      reason="Parquet doesn't support nanosecond precision"),
    (pd.DataFrame({'x': [3, 2, 1]}).astype('M8[us]'), {}, {}),
    (pd.DataFrame({'x': [3, 2, 1]}).astype('M8[ms]'), {}, {}),
    (pd.DataFrame({'x': [3, 2, 1]}).astype('uint16'), {}, {}),
    (pd.DataFrame({'x': [3, 2, 1]}).astype('float32'), {}, {}),
    (pd.DataFrame({'x': [3, 1, 2]}, index=[3, 2, 1]), {}, {}),
    (pd.DataFrame({'x': [3, 1, 5]}, index=pd.Index([1, 2, 3], name='foo')), {}, {}),
    (pd.DataFrame({'x': [1, 2, 3],
                   'y': [3, 2, 1]}), {}, {}),
    (pd.DataFrame({'x': [1, 2, 3],
                   'y': [3, 2, 1]}, columns=['y', 'x']), {}, {}),
    (pd.DataFrame({'0': [3, 2, 1]}), {}, {}),
    (pd.DataFrame({'x': [3, 2, None]}), {}, {}),
    (pd.DataFrame({'-': [3., 2., None]}), {}, {}),
    (pd.DataFrame({'.': [3., 2., None]}), {}, {}),
    (pd.DataFrame({' ': [3., 2., None]}), {}, {}),
])
def test_roundtrip(tmpdir, df, write_kwargs, read_kwargs):
    check_fastparquet()
    tmp = str(tmpdir)
    if df.index.name is None:
        df.index.name = 'index'
    ddf = dd.from_pandas(df, npartitions=2)

    dd.to_parquet(ddf, tmp, **write_kwargs)
    ddf2 = dd.read_parquet(tmp, index=df.index.name, **read_kwargs)
    assert_eq(ddf, ddf2)


def test_categories(tmpdir):
    check_fastparquet()
    fn = str(tmpdir)
    df = pd.DataFrame({'x': [1, 2, 3, 4, 5],
                       'y': list('caaab')})
    ddf = dd.from_pandas(df, npartitions=2)
    ddf['y'] = ddf.y.astype('category')
    ddf.to_parquet(fn)
    ddf2 = dd.read_parquet(fn, categories=['y'])
    with pytest.raises(NotImplementedError):
        ddf2.y.cat.categories
    assert set(ddf2.y.compute().cat.categories) == {'a', 'b', 'c'}
    cats_set = ddf2.map_partitions(lambda x: x.y.cat.categories).compute()
    assert cats_set.tolist() == ['a', 'c', 'a', 'b']
    assert_eq(ddf.y, ddf2.y, check_names=False)
    with pytest.raises(TypeError):
        # attempt to load as category that which is not so encoded
        ddf2 = dd.read_parquet(fn, categories=['x']).compute()

    with pytest.raises(ValueError):
        # attempt to load as category unknown column
        ddf2 = dd.read_parquet(fn, categories=['foo'])


def test_empty_partition(tmpdir, engine):
    fn = str(tmpdir)
    df = pd.DataFrame({"a": range(10), "b": range(10)})
    ddf = dd.from_pandas(df, npartitions=5)

    ddf2 = ddf[ddf.a <= 5]
    ddf2.to_parquet(fn, engine=engine)

    ddf3 = dd.read_parquet(fn, engine=engine)
    sol = ddf2.compute()
    assert_eq(sol, ddf3, check_names=False, check_index=False)


def test_timestamp_index(tmpdir, engine):
    fn = str(tmpdir)
    df = tm.makeTimeDataFrame()
    df.index.name = 'foo'
    ddf = dd.from_pandas(df, npartitions=5)
    ddf.to_parquet(fn, engine=engine)
    ddf2 = dd.read_parquet(fn, engine=engine)
    assert_eq(df, ddf2)


def test_to_parquet_default_writes_nulls(tmpdir):
    check_fastparquet()
    check_pyarrow()
    fn = str(tmpdir.join('test.parquet'))

    df = pd.DataFrame({'c1': [1., np.nan, 2, np.nan, 3]})
    ddf = dd.from_pandas(df, npartitions=1)

    ddf.to_parquet(fn)
    table = pq.read_table(fn)
    assert table[1].null_count == 2


def test_partition_on(tmpdir):
    check_fastparquet()
    tmpdir = str(tmpdir)
    df = pd.DataFrame({'a': np.random.choice(['A', 'B', 'C'], size=100),
                       'b': np.random.random(size=100),
                       'c': np.random.randint(1, 5, size=100)})
    d = dd.from_pandas(df, npartitions=2)
    d.to_parquet(tmpdir, partition_on=['a'])
    out = dd.read_parquet(tmpdir, engine='fastparquet').compute()
    for val in df.a.unique():
        assert set(df.b[df.a == val]) == set(out.b[out.a == val])


def test_filters(tmpdir):
    check_fastparquet()
    fn = str(tmpdir)

    df = pd.DataFrame({'at': ['ab', 'aa', 'ba', 'da', 'bb']})
    ddf = dd.from_pandas(df, npartitions=1)

    # Ok with 1 partition and filters
    ddf.repartition(npartitions=1, force=True).to_parquet(fn, write_index=False)
    ddf2 = dd.read_parquet(fn, index=False,
                           filters=[('at', '==', 'aa')]).compute()
    assert_eq(ddf2, ddf)

    # with >1 partition and no filters
    ddf.repartition(npartitions=2, force=True).to_parquet(fn)
    dd.read_parquet(fn).compute()
    assert_eq(ddf2, ddf)

    # with >1 partition and filters using base fastparquet
    ddf.repartition(npartitions=2, force=True).to_parquet(fn)
    df2 = fastparquet.ParquetFile(fn).to_pandas(filters=[('at', '==', 'aa')])
    assert len(df2) > 0

    # with >1 partition and filters
    ddf.repartition(npartitions=2, force=True).to_parquet(fn)
    dd.read_parquet(fn, filters=[('at', '==', 'aa')]).compute()
    assert len(ddf2) > 0


@pytest.mark.parametrize('get', [dask.threaded.get, dask.multiprocessing.get])
def test_to_parquet_lazy(tmpdir, get):
    check_fastparquet()
    tmpdir = str(tmpdir)
    df = pd.DataFrame({'a': [1, 2, 3, 4],
                       'b': [1., 2., 3., 4.]})
    df.index.name = 'index'
    ddf = dd.from_pandas(df, npartitions=2)
    value = ddf.to_parquet(tmpdir, compute=False)

    assert hasattr(value, 'dask')
    value.compute(get=get)
    assert os.path.exists(tmpdir)

    ddf2 = dd.read_parquet(tmpdir)

    assert_eq(ddf, ddf2)


def test_timestamp96(tmpdir):
    check_fastparquet()
    fn = str(tmpdir)
    df = pd.DataFrame({'a': ['now']}, dtype='M8[ns]')
    ddf = dd.from_pandas(df, 1)
    ddf.to_parquet(fn, write_index=False, times='int96')
    pf = fastparquet.ParquetFile(fn)
    assert pf._schema[1].type == fastparquet.parquet_thrift.Type.INT96
    out = dd.read_parquet(fn).compute()
    assert_eq(out, df)


def test_drill_scheme(tmpdir):
    check_fastparquet()
    fn = str(tmpdir)
    N = 5
    df1 = pd.DataFrame({c: np.random.random(N)
                        for i, c in enumerate(['a', 'b', 'c'])})
    df2 = pd.DataFrame({c: np.random.random(N)
                        for i, c in enumerate(['a', 'b', 'c'])})
    files = []
    for d in ['test_data1', 'test_data2']:
        dn = os.path.join(fn, d)
        if not os.path.exists(dn):
            os.mkdir(dn)
        files.append(os.path.join(dn, 'data1.parq'))

    fastparquet.write(files[0], df1)
    fastparquet.write(files[1], df2)

    df = dd.read_parquet(files)
    assert 'dir0' in df.columns
    out = df.compute()
    assert 'dir0' in out
    assert (np.unique(out.dir0) == ['test_data1', 'test_data2']).all()


def test_parquet_select_cats(tmpdir):
    check_fastparquet()
    fn = str(tmpdir)
    df = pd.DataFrame({
        'categories': pd.Series(
            np.random.choice(['a', 'b', 'c', 'd', 'e', 'f'], size=100),
            dtype='category'),
        'ints': pd.Series(list(range(0, 100)), dtype='int'),
        'floats': pd.Series(list(range(0, 100)), dtype='float')})

    ddf = dd.from_pandas(df, 1)
    ddf.to_parquet(fn)
    rddf = dd.read_parquet(fn, columns=['ints'])
    assert list(rddf.columns) == ['ints']
    rddf = dd.read_parquet(fn)
    assert list(rddf.columns) == list(df)


@pytest.mark.parametrize('compression,', ['default', None, 'gzip', 'snappy'])
def test_writing_parquet_with_compression(tmpdir, compression, engine):
    fn = str(tmpdir)

    if engine == 'fastparquet' and compression == 'snappy':
        pytest.importorskip('snappy')

    df = pd.DataFrame({'x': ['a', 'b', 'c'] * 10,
                       'y': [1, 2, 3] * 10})
    ddf = dd.from_pandas(df, npartitions=3)

    ddf.to_parquet(fn, compression=compression, engine=engine)
    out = dd.read_parquet(fn, engine=engine)
    assert_eq(out, df, check_index=(engine != 'fastparquet'))
