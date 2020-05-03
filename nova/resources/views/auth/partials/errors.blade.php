@if ($errors->any())
<p class="text-center font-semibold text-danger my-3">
    @if ($errors->has('email'))
        {{ $errors->first('email') }}
    @else
        {{ $errors->first('password') }}
    @endif
    </p>
@endif
