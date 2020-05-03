<?php

namespace Laravel\Nova\Tests\Unit;

use Illuminate\Support\Collection;
use Laravel\Nova\FilterDecoder;
use Laravel\Nova\Query\ApplyFilter;
use Laravel\Nova\Tests\Fixtures\IdFilter;
use Laravel\Nova\Tests\IntegrationTest;

class DecodesFilterTest extends IntegrationTest
{
    public function test_decodes_filters_correctly()
    {
        $filterString = 'W3siY2xhc3MiOiJIZW1wXFxDdXN0b21GaWx0ZXJcXEN1c3RvbUZpbHRlciIsInZhbHVlIjoiIn0seyJjbGFzcyI6IkFwcFxcTm92YVxcRmlsdGVyc1xcRGF0ZUZpbHRlciIsInZhbHVlIjoiMjAxOS0xMC0xNCJ9LHsiY2xhc3MiOiJBcHBcXE5vdmFcXEZpbHRlcnNcXEFkbWluRmlsdGVyIiwidmFsdWUiOnsiYWRtaW4iOnRydWUsIm5vcm1pZSI6ZmFsc2V9fSx7ImNsYXNzIjoiQXBwXFxOb3ZhXFxGaWx0ZXJzXFxVc2VyRmlsdGVyIiwidmFsdWUiOiJhY3RpdmUifV0';
        $decoder = new FilterDecoder($filterString);

        $this->assertEquals([
            [
                'class' => 'Hemp\CustomFilter\CustomFilter',
                'value' => '',
            ],
            [
                'class' => 'App\Nova\Filters\DateFilter',
                'value' => '2019-10-14',
            ],
            [
                'class' => 'App\Nova\Filters\AdminFilter',
                'value' => [
                    'admin' => true,
                    'normie' => false,
                ],
            ],
            [
                'class' => 'App\Nova\Filters\UserFilter',
                'value' => 'active',
            ],
        ], $decoder->decodeFromBase64String());
    }

    public function test_empty_filter_strings_return_empty_array()
    {
        $filterString = '';
        $decoder = new FilterDecoder($filterString);

        $this->assertEquals([], $decoder->decodeFromBase64String());
    }

    public function test_decoding_and_returning_applied_filters_for_request()
    {
        $filterString = base64_encode(json_encode([
            [
                'class' => IdFilter::class,
                'value' => '1',
            ],
        ], true));

        $availableFilters = collect([new IdFilter]);

        $decoder = new FilterDecoder($filterString, $availableFilters);

        $filters = $decoder->filters();
        $this->assertInstanceOf(Collection::class, $filters);
        $this->assertCount(1, $filters);
        $this->assertInstanceOf(ApplyFilter::class, $filters->first());
    }
}
