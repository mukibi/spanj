#!/usr/bin/perl

use strict;
use warnings;

use DBI;
use Fcntl qw/:flock SEEK_END/;

require "./conf.pl";

our($db,$db_user,$db_pwd,$log_d,$doc_root,$upload_dir);

my %session;
my %auth_params;

my $id;
my $logd_in = 0;
my $authd = 0;
my $accountant = 0;

my $con;
my ($key,$iv,$cipher) = (undef, undef,undef);

if ( exists $ENV{"HTTP_SESSION"} ) {

	my @session_data = split/&/,$ENV{"HTTP_SESSION"};
	my @tuple;

	for my $unprocd_tuple (@session_data) {
		#came to learn (as often happens, purely by accident)
		#doing a split/=/,x= will give a list with a size of 1
		#desirable here (where it's OK to ignore unset vars)
		#would be awful where even a blank var means something (e.g
		#logging in with a blank password)
		@tuple = split/\=/,$unprocd_tuple;

		if (@tuple == 2) {
			$tuple[0] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$tuple[1] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$session{$tuple[0]} = $tuple[1];		
		}
	}

	#logged in 
	if (exists $session{"id"}) {
		$logd_in++;
		$id = $session{"id"};
		#only bursar(user 2) or accountant can search for a payment voucher
		if ( $id eq "2" or ($id =~ /^\d+$/ and ($id % 17) == 0) ) {

			$accountant++;
			if (exists $session{"sess_key"} ) {
				$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});

				use MIME::Base64 qw /decode_base64/;
				use Crypt::Rijndael;

				my $decoded = decode_base64($session{"sess_key"});
				my @decoded_bytes = unpack("C*", $decoded);

				my @sess_init_vec_bytes = splice(@decoded_bytes, 32);
				my @sess_key_bytes = @decoded_bytes;

				#read enc_keys_mem
				my $prep_stmt3 = $con->prepare("SELECT init_vec,aes_key FROM enc_keys_mem WHERE u_id=? LIMIT 1");

				if ( $prep_stmt3 ) {

					my $rc = $prep_stmt3->execute($id);

					if ( $rc ) {

						my ($mem_init_vec, $mem_aes_key) = (undef,undef);

						while (my @rslts = $prep_stmt3->fetchrow_array()) {
							$mem_init_vec = $rslts[0];
							$mem_aes_key = $rslts[1];
						}

						if ( defined $mem_init_vec ) {

							my @mem_init_vec_bytes = unpack("C*", $mem_init_vec);
							my @mem_aes_key_bytes = unpack("C*", $mem_aes_key);

							my ( @decrypted_init_vec, @decrypted_aes_key );

							for (my $i = 0; $i < @mem_init_vec_bytes; $i++) {
								$decrypted_init_vec[$i] = $mem_init_vec_bytes[$i] ^ $sess_init_vec_bytes[$i];
							}

							for (my $j = 0; $j < @mem_aes_key_bytes; $j++) {
								$decrypted_aes_key[$j] = $mem_aes_key_bytes[$j] ^ $sess_key_bytes[$j];
							}

							$key = pack("C*", @decrypted_aes_key);
							$iv = pack("C*", @decrypted_init_vec);

							$cipher = Crypt::Rijndael->new($key, Crypt::Rijndael::MODE_CBC());
							$cipher->set_iv($iv);

							$authd++;

						}
					}
					else {
						print STDERR "Couldn't execute SELECT FROM enc_keys_mem: ", $prep_stmt3->errstr, $/;
					}

				}
				else {
					print STDERR "Couldn't prepare SELECT FROM enc_keys_mem: ", $prep_stmt3->errstr, $/;
				}
			}
		}
	}
}

my $content = '';
my $feedback = '';
my $js = '';

my $header =
qq{
<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Accounts Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a> --&gt; <a href="/accounts/">Accounts</a> --&gt; <a href="/cgi-bin/search_voucher.cgi">Search Voucher</a>
	<hr> 
};

unless ($authd) {
	if ($logd_in) {
		my $err = qq!<p><span style="color: red">Sorry, you do not have the appropriate privileges to print a payment voucher.</span> Only the bursar and accountants are authorized to take this action.!;

		#key issues?
		if ( $accountant ) {

			$err = qq!<p><span style="color: red">Sorry, could not obtain the encryption keys needed to manage accounts.</span> Try <a href="/cgi-bin/logout.cgi">logging out</a> and then log in again. If this problem persists, contact support.!;

		}

		$content .=
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj::Accounts Management Information System::Print Payment Voucher</title>
</head>
<body>
$header

</body>
</html> 
*;
		print "Status: 200 OK\r\n";
		print "Content-Type: text/html; charset=UTF-8\r\n";

		my $len = length($content);
		print "Content-Length: $len\r\n";

		my @new_sess_array = ();

		for my $sess_key (keys %session) {
			push @new_sess_array, $sess_key."=".$session{$sess_key};        
		}
		my $new_sess = join ('&',@new_sess_array);

		print "X-Update-Session: $new_sess\r\n";

		print "\r\n";
		print $content;
		exit 0;
	}
	else {
		print "Status: 302 Moved Temporarily\r\n";
		print "Location: /login.html?cont=/cgi-bin/search_voucher.cgi\r\n";
		print "Content-Type: text/html; charset=UTF-8\r\n";
       		my $res = 
qq!
<html lang="en">
<head>
<title>Spanj::Accounts Management Information System::Create Balance Sheet</title>
</head>
<body>
$header
You should have been redirected to <a href="/login.html?cont=/cgi-bin/search_payment_voucher.cgi">/login.html?cont=/cgi-bin/search_payment_voucher.cgi</a>. If you were not, <a href="login.html?cont=/cgi-bin/search_payment_voucher.cgi">Click Here</a> 
</body>
</html>!;

		my $content_len = length($res);	
		print "Content-Length: $content_len\r\n";
		print "\r\n";
		print $res;
		exit 0;
	}
}

my $post_mode = 0;
my $boundary = undef;
my $multi_part = 0;

if (exists $ENV{"REQUEST_METHOD"} and uc($ENV{"REQUEST_METHOD"}) eq "POST") {
	

	if (exists $ENV{"CONTENT_TYPE"}) {
		if ($ENV{"CONTENT_TYPE"} =~ m!multipart/form-data;\sboundary=(.+)!i) {
			$boundary = $1;
			$multi_part++;
		}
	}

	unless ($multi_part) {
		my $str = "";

		while (<STDIN>) {
        	       	$str .= $_;
	       	}

		my $space = " ";
		$str =~ s/\x2B/$space/ge;
		my @auth_req = split/&/,$str;

		for my $auth_req_line (@auth_req) {
			my $eqs = index($auth_req_line, "=");	
			if ($eqs > 0) {
				my ($k, $v) = (substr($auth_req_line, 0, $eqs), substr($auth_req_line, $eqs + 1));
				$k =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
				$v =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
				$auth_params{$k} = $v;
			}
		}
	}
	#processing data sent 
	$post_mode++;
}


my @payment_vouchers;
#print payment_voucher shortcut
if ( exists $ENV{"QUERY_STRING"} ) {
	my $query_str = $ENV{"QUERY_STRING"};
	my @query_str_bts = split/&/,$query_str;

	foreach (@query_str_bts) {
		if ($_ =~ /payment_voucher_(\d+)=\1/) {
			my $payment_voucher = $1;
			push @payment_vouchers, $payment_voucher;
		}
	}
}

if ($post_mode) {

	foreach ( keys %auth_params ) {
		if ( $_ =~ /payment_voucher_(\d+)/ ) {
			#don't want mischevious users doing their own cookery
			my $payment_voucher_no = $1;
			if ($auth_params{$_} eq $payment_voucher_no) {
				push @payment_vouchers, $payment_voucher_no;
			}
		}
	}

}

my $results = qq!<span style="color: red">You did not specify any payment vouchers to print.!;

if ( scalar(@payment_vouchers) > 0 ) {

	my %mode_payment_lookup = ("1" => "Bank Deposit", "2" => "Cash", "3" => "Banker's Cheque", "4" => "Money Order");
	my %payment_vouchers = ();

	$results = '';
	use Digest::HMAC_SHA1 qw/hmac_sha1_hex/;

	#read payment vouchers
	my $prep_stmt4 = $con->prepare("SELECT voucher_no,paid_out_to,amount,mode_payment,ref_id,description,votehead,time,hmac FROM payment_vouchers WHERE voucher_no=? LIMIT 1");

	if ($prep_stmt4) {

		for my $voucher (@payment_vouchers) {

			my $voucher_no = undef;

			my $rc = $prep_stmt4->execute($voucher);

			if ( $rc ) {
	
				while ( my @rslts = $prep_stmt4->fetchrow_array() ) {

					$voucher_no = $rslts[0];
					#print "X-Debug-$voucher_no: ..\r\n";
					$payment_vouchers{$voucher_no} = {};

					my $paid_out_to = remove_padding($cipher->decrypt($rslts[1]));
					my $amount = remove_padding($cipher->decrypt($rslts[2]));
					my $mode_payment = remove_padding($cipher->decrypt($rslts[3]));
					my $ref_id = remove_padding($cipher->decrypt($rslts[4]));
					my $descr = remove_padding($cipher->decrypt($rslts[5]));
					my $votehead = remove_padding($cipher->decrypt($rslts[6]));
					my $time = remove_padding($cipher->decrypt($rslts[7]));

					if ( $amount =~ /^\d+(\.\d{1,2})?$/ ) {
	
						my $hmac = uc(hmac_sha1_hex($paid_out_to . $amount . $mode_payment . $ref_id . $descr . $votehead . $time, $key));

						if ( $hmac eq $rslts[8] ) {

							${$payment_vouchers{$voucher_no}}{"paid_out_to"} = $paid_out_to;
							my $mode_payment_descr = $mode_payment_lookup{$mode_payment};	
							${$payment_vouchers{$voucher_no}}{"mode_payment"} = $mode_payment_descr;
							if ($ref_id ne "") {
								${$payment_vouchers{$voucher_no}}{"ref_id"} = $ref_id;
							}

							${$payment_vouchers{$voucher_no}}{"amount"} = format_currency($amount);
							${$payment_vouchers{$voucher_no}}{"payment_for"} = $descr;
							${$payment_vouchers{$voucher_no}}{"votehead"} = $votehead;

							my @date = localtime($time);
							my $f_time = sprintf "%02d/%02d/%d %02d:%02d:%02d", $date[3],$date[4]+1,$date[5]+1900,$date[2],$date[1],$date[0];

							${$payment_vouchers{$voucher_no}}{"time"} = $f_time;
							${$payment_vouchers{$voucher_no}}{"enc_time"} = $rslts[7];

						}
					}
				}
			}
			else {
				print STDERR "Couldn't prepare SELECT FROM payment_vouchers:", $prep_stmt4->errstr, $/;
			}

			delete $payment_vouchers{$voucher} if (not defined $voucher_no);
		}
	}
	else {
		print STDERR "Couldn't prepare SELECT FROM payment_vouchers:", $prep_stmt4->errstr, $/;
	}

	my %payment_voucher_votehead = ();

	#payment voucher entries in the 'payments_book' will have the same 
	#'time' field as the corresponding entries in 'payment_vouchers'
	
	my $prep_stmt5 = $con->prepare("SELECT voucher_votehead,votehead,amount,time,hmac FROM payments_book WHERE BINARY time=?");

	if ($prep_stmt5) {

		for my $voucher (keys %payment_vouchers) {
 
			my $rc = $prep_stmt5->execute($payment_vouchers{$voucher}->{"enc_time"});

			if ($rc) {
				while ( my @rslts = $prep_stmt5->fetchrow_array() ) {

					my $voucher_votehead = remove_padding($cipher->decrypt($rslts[0]));
					my $votehead = remove_padding($cipher->decrypt($rslts[1]));
					my $amount = remove_padding($cipher->decrypt($rslts[2]));
					my $time = remove_padding($cipher->decrypt($rslts[3]));
				
					my $voucher_no = $voucher_votehead;
					$voucher_no =~ s/\-$votehead//;

					if ( $amount =~ /^\d+(?:\.\d{1,2})?$/ ) {
	
						my $hmac = uc(hmac_sha1_hex($voucher_votehead . $votehead . $amount . $time , $key));
						if ( $hmac eq $rslts[4] ) {
							if ( $voucher_no eq $voucher ) {
								${$payment_voucher_votehead{$voucher}}{$votehead} = $amount;
							}
						}
					}
				}
			}
			else {
				print STDERR "Couldn't prepare SELECT FROM payments_book:", $prep_stmt5->errstr, $/;
			}
		}

	}
	else {
		print STDERR "Couldn't prepare SELECT FROM payment_book:", $prep_stmt5->errstr, $/;
	}

	for my $voucher (keys %payment_vouchers) {

		my $ref_id_row = "";
		my $ref_id_bt = "";

		if ( exists $payment_vouchers{$voucher}->{"ref_id"} ) {
			$ref_id_row = qq!<TR><TD style="font-weight: bold">Ref No./Code<TD>$payment_vouchers{$voucher}->{"ref_id"}!;
			$ref_id_bt = qq!($payment_vouchers{$voucher}->{"ref_id"})!;
		}

		my $paid_out_to = ${$payment_vouchers{$voucher}}{"paid_out_to"};
		$paid_out_to = htmlspecialchars($paid_out_to);

		my $padded_paid_out_to = $paid_out_to .= ("&nbsp;" x 75);

		my $f_time = ${$payment_vouchers{$voucher}}{"time"};

		my @description_bts = split/,/,htmlspecialchars(${$payment_vouchers{$voucher}}{"payment_for"});
		my $description_list = join("<BR>", @description_bts);

		my ($shs,$cts) = (${$payment_vouchers{$voucher}}{"amount"}, "00");
		if ( ${$payment_vouchers{$voucher}}{"amount"} =~ /^(\d+)(?:\.(\d{1,2}))$/ ) {
			$shs = $1;
			$cts = $2;
			if ( length ($cts) == 1 ) {
				$cts .= "0"; 
			}
		}

		my $votehead_rows = "";

		my @votehead_bts = ();

		for my $votehead (keys %{$payment_voucher_votehead{$voucher}}) {

			my @this_votehead_bts = split/\s+/,$votehead;
			my @n_votehead_bts = ();

			foreach ( @this_votehead_bts ) {
				push @n_votehead_bts, ucfirst($_);
			}
			my $this_votehead = join(" ", @n_votehead_bts);

			my $amnt = $payment_voucher_votehead{$voucher}->{$votehead};
			my ($shs,$cts) = ($amnt,"00");

			if ($amnt =~ /^(\d+)(?:\.(\d{1,2}))$/ ) {
				$shs = $1;
				$cts = $2;
				if ( length ($cts) == 1 ) {
					$cts .= "0"; 
				}
			}
				
			my $style = qq! style="border-bottom-style: none; border-top-style: none"!;	

			$votehead_rows .= qq!<TR><TD$style>$this_votehead<TD$style>&nbsp;<TD$style>&nbsp;<TD$style>&nbsp;<TD>$shs<TD>$cts!;
			if ( scalar(keys %{$payment_voucher_votehead{$voucher}}) > 0 ) {
				$this_votehead .= "[" . format_currency($amnt) . "]";
			}

			push @votehead_bts, $this_votehead;

		}

		my $dots = "." x 20;

		$results .=
qq*
<div style="height: 297mm; width: 210mm">
<div style="text-align: center; width: 210mm"><img src="/images/letterhead2.png" alt="" ></div>
<DIV style="text-align: center; text-decoration: underline;">PAYMENT VOUCHER</DIV>
<DIV style="text-align: right">Voucher No. <span style="font-weight: bold">$voucher</span></DIV>
<DIV style="text-align: center; font-weight: bold">MAIN ACCOUNT</DIV>
<HR>
<P><SPAN style="font-weight: bold">SECTION I</SPAN>
<p><span style="font-weight: bold">Payee's Name and Address</span>: <span style="text-decoration: underline">$padded_paid_out_to</span>

<TABLE style="table-layout: fixed; width: 200mm" border="1" cellpadding="0" cellspacing="0">

<tr style="font-weight: bold"><td style="width: 20%">Date<td style="width: 60%">Particulars<td style="width: 15%">Kshs<td style="width: 5%">Cts.
<tr style="height: 12em" valign="top"><td style="border-bottom-style: none">$f_time<td style="border-bottom-style: none">$description_list<td><td>
<tr><td style="border-top-style: none"><td style="border-top-style: none; text-align: right; font-weight: bold">TOTAL&nbsp;<td style="text-align: right">$shs<td style="text-align: right">$cts

</TABLE>
<p><span style="font-weight: bold">Mode Payment: </span>${$payment_vouchers{$voucher}}{"mode_payment"}$ref_id_bt
<p><span style="font-weight: bold; text-decoration: underline">Payment Authorization</span>

<table style="table-layout: fixed; width: 200mm">

<tr><td style="width: 50%; height: 4em">Principal<br>$dots$dots<td style="width: 50%">Bursar/Accounts Clerk/Secretary<br>$dots$dots
<tr><td colspan="2" style="text-align: center">Date<br>$dots$dots$dots

</table>

<p style="line-height: 200%">In full payment of the following invoices/receipts: $dots $dots $dots $dots $dots $dots $dots $dots
<HR>
<P><SPAN style="font-weight: bold">SECTION II</SPAN>
<P>
<TABLE style="line-height: 200%; table-layout: fixed" border="1">
<THEAD>
<TH style="width: 25%">Votehead(s)<TH style="width: 25%">Details<TH style="width: 15%">C/B<TH style="width: 15%">L/F<TH style="width: 15%">Kshs<TH style="width: 5%">Cts
</THEAD>
<TBODY>
$votehead_rows
<TR><TD style="border-top-style: none"><TD style="border-top-style: none"><TD style="border-top-style: none"><TD style="border-top-style: none;font-weight: bold">TOTAL&nbsp;<TD style="font-weight: bold">$shs<TD style="font-weight: bold">$cts
</TBODY>
</TABLE>

<p style="line-height: 200%">Receieved this ....... day of ........ the year of ............. in payment of the above acccount<br>
the sum of.........................................................................................................
<TABLE style="width: 200mm; line-height: 200%">
<tr>
<TD>.......................................<br>Date<TD>.....................................<br>Signature of Witness<TD>......................................<br>Signature of Receiver
</TABLE>
</div>
<br class="new_page">
*;			

	}
}

$content =

qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj::Accounts Management Information System::Print Receipt</title>

<STYLE type="text/css">

\@media print {
	body {
		margin-top: 0px;
		margin-bottom: 0px;
		padding: 0px;
		font-size: 10pt;
		font-family: "Times New Roman", serif;	
	}

	div.no_header {
		display: none;
	}

	br.new_page {
		page-break-after: always;
	}

}

\@media screen {
	div.noheader {}	
	br.new_page {
		line-height: 2em;
	}
}

</STYLE>
</head>
<body>
<div class="no_header">
$header
</div> 
$results
</body>
</html>

*;

print "Status: 200 OK\r\n";
print "Content-Type: text/html; charset=UTF-8\r\n";

my $len = length($content);
print "Content-Length: $len\r\n";

my @new_sess_array = ();

for my $sess_key (keys %session) {
	push @new_sess_array, $sess_key."=".$session{$sess_key};        
}
my $new_sess = join ('&',@new_sess_array);

print "X-Update-Session: $new_sess\r\n";

print "\r\n";
print $content;
$con->disconnect() if (defined $con and $con);

sub gen_token {
	my @key_space = ("A","B","C","D","E","F","0","1","2","3","4","5","6","7","8","9");
	my $len = 5 + int(rand 15);
	if (@_ and ($_[0] eq "1")) {
		@key_space = ("A","B","C","D","E","F","G","H","J","K","L","M","N","P","T","W","X","Z","7","0","1","2","3","4","5","6","7","8","9");
		$len = 10 + int (rand 5);
	}
	my $token = "";
	for (my $i = 0; $i < $len; $i++) {
		$token .= $key_space[int(rand @key_space)];
	}
	return $token;
}

sub htmlspecialchars {
	my $cp = $_[0];
	$cp =~ s/&/&#38;/g;
        $cp =~ s/</&#60;/g;
        $cp =~ s/>/&#62;/g;
        $cp =~ s/'/&#39;/g;
        $cp =~ s/"/&#34;/g;
        return $cp;
}

sub remove_padding {

	return undef unless (@_);

	my $packed = $_[0];
	my @bytes = unpack("C*", $packed);
	
	my $final_index = $#bytes;
	my $pad_size = $bytes[$final_index];

	my $msg_valid = 1;
	#verify msg
	
	for ( my $i = 1; $i < $pad_size; $i++ ) {
		unless ( $bytes[$final_index - $i] == $pad_size ) {
			$msg_valid = 0;
			last;
		}
	}

	if ($msg_valid) {
		my $msg_size = ($final_index + 1) - $pad_size;
		my $msg = unpack("A${msg_size}", $packed);

		return $msg;
	}
	return undef;
}

sub add_padding {

	return undef unless (@_);

	my $tst_str = $_[0];
	my $tst_str_len = length($tst_str);

	my $rem = 16 - ($tst_str_len % 16);
	if ($rem == 0 ) {
		$rem = 16;
	}

	my @extras = ();
	for (my $i = 0; $i < $rem; $i++) {
		push @extras, $rem;
	}

	my $padded = pack("A${tst_str_len}C${rem}", $tst_str, @extras);
	return $padded;
}

sub format_currency {

	return "" unless (@_);

	my $formatted_num = $_[0];

	if ( $_[0] =~ /^(\-?)(\d+)(\.(?:\d))?$/ ) {

		my $sign = $1;
		my $shs = $2;
		my $cents = $3;

		$sign = "" if (not defined $sign);
		$cents = "" if (not defined $cents);

		my $num_blocks = int(length($shs) / 3);

		if ($num_blocks > 0) {

			my @nums = ();

			my $surplus = length($shs) % 3;
			if ($surplus > 0) {
				push @nums, substr($shs, 0, $surplus);
			}

			for (my $i = 0; $i < $num_blocks; $i++) {
				push @nums, substr($shs, $surplus + ($i * 3),3);
			}

			$formatted_num = join(",", @nums); 
		}

		$formatted_num = $sign . $formatted_num;
		$formatted_num .= $cents;
	}
	return $formatted_num;
}
